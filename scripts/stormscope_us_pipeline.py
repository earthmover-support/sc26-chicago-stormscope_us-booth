"""StormScope US nowcasting pipeline for the SC26 Chicago booth.

GOES-19 ABI CONUS observations (NOAA, AWS) -> Earth2Studio inference
(StormScopeGOES, `3km_10min_flash`) -> streaming Icechunk/Arraylake publication
-> tile-ready RGB composites.

It finds the freshest complete
input window by listing NOAA's `noaa-goes19` bucket (`latest_goes_slot`), stores two
composites, `true_color` (day) and `clean_ir` (colour-enhanced Clean IR 10.3 um, for
night), and writes one Icechunk commit per init. Each 10-minute rollout step is handed
to the backend's background writers as it is produced, so uploads overlap inference,
and the commit at the end of the rollout publishes the whole init at once. It writes to
the root group of `nvidia/sc26-chicago-stormscope_us-booth` (see ARRAYLAKE_REPO below).
Runs accumulate: each one appends its init to `time` in that same commit, so readers
never see a partly written init.

Without --start-time the script runs continuously: the model is loaded once
(`StormScopeUSPipeline`), and `main()` polls the bucket, starting a new run whenever a
fresher initial condition becomes available. With --start-time it runs that one init
and exits.

The model works on the HRRR Lambert conformal grid (3 km, CONUS), not the GOES fixed
grid: `GOES` data is interpolated onto it inside the model (`build_input_interpolator`).
`--region` restricts the run to a lat/lon box (Flash only, `set_domain`); the stored
cube is then the cropped output, not the padded model input.

Publishing goes through Earth2Studio's `earth2studio.io.IceChunkBackend` directly:
`arraylake.Client.get_icechunk_storage(name)` returns a plain `icechunk.Storage`, which
`IceChunkBackend`'s `storage` parameter already accepts (earth2studio >= 0.20 also
reopens repos holding the scalar CF grid mapping). `add_coord()` writes the 2-D `lat`/`lon` without them being taken
for new index dimensions.

`add_array()` forwards unrecognized kwargs straight to `zarr.Group.create_array()`,
which has no `attrs` parameter -- attrs are set via `.attrs.update()` after creation.

Env vars:
    ARRAYLAKE_API_TOKEN
        only needed with --publish-target arraylake
    (GOES data is public; no credentials needed)

Install:
    uv sync  # add --extra gpu on a linux+CUDA host

Usage:
    python scripts/stormscope_us_pipeline.py --n-steps 3  # runs until interrupted
    python scripts/stormscope_us_pipeline.py --start-time 2026-11-16T18:00 --n-steps 12  # one run
    python scripts/stormscope_us_pipeline.py --region 36,46,-96,-82  # Midwest box only
    python scripts/stormscope_us_pipeline.py --publish-target arraylake
    python scripts/stormscope_us_pipeline.py --help
"""

import argparse
import os
import re
import time
from collections import OrderedDict
from datetime import UTC, datetime, timedelta

import numpy as np
import pyproj

# CF grid mapping of the HRRR grid StormScope runs on: Lambert conformal, single
# standard parallel 38.5N, central meridian 97.5W, sphere of radius 6371229 m. `x`/`y`
# are metres from the projection origin (east / north positive), as in
# `earth2studio.data.HRRR.HRRR_X/Y`.
GRID_MAPPING = "hrrr_lambert_conformal"
HRRR_LCC = {
    "long_name": "HRRR Lambert conformal conic projection",
    "grid_mapping_name": "lambert_conformal_conic",
    "standard_parallel": 38.5,
    "longitude_of_central_meridian": 262.5,
    "latitude_of_projection_origin": 38.5,
    "false_easting": 0.0,
    "false_northing": 0.0,
    "earth_radius": 6371229.0,
}
HRRR_CRS = pyproj.CRS.from_cf(HRRR_LCC)
HRRR_LCC["crs_wkt"] = HRRR_CRS.to_wkt()  # for GDAL/rioxarray

# ============================================================================
# COMPOSITES (pure numpy; tested in tests/test_composites.py)
# ============================================================================
RGB_VALUES = np.array(["red", "green", "blue"])
# The tiles service takes the `rgb` dim as R, G, B by position and reads only
# `valid_min`/`valid_max` (the byte stretch).
RGB_BAND_ATTRS = {"long_name": "colour band", "color_interpretation": " ".join(RGB_VALUES)}
# Both composites are stored as bytes: 1..255 for data, 0 for missing (outside the
# GOES view / requested region, or a step not written yet), as the Zarr v3 `fill_value`.
# No CF `_FillValue` attribute: the tiles service decodes it by upcasting to float32.
RGB_DTYPE = "uint8"
RGB_FILL = 0
RGB_ENCODING = {"valid_min": 0, "valid_max": 255}

# ABI L2 CMI: C01-C06 are reflectance factors (0..1), C07-C16 brightness temperatures (K).
TRUE_COLOR_CHANNELS = ["abi02c", "abi03c", "abi01c"]  # red 0.64, veggie 0.86, blue 0.47 um
CLEAN_IR_CHANNEL = "abi13c"  # Clean IR longwave window 10.35 um
TRUE_COLOR_GAMMA = 2.2

# Enhanced Clean IR colour table: grey for everything warmer than -30 C (warm = dark,
# so the ground is near-black at night and low cloud grey), colour for cold cloud tops.
# (brightness temperature K, (R, G, B)), linear in between, clamped at both ends.
CLEAN_IR_TABLE = [
    (183.15, (255, 255, 255)),  # -90 C  overshooting tops
    (193.15, (120, 0, 0)),  # -80 C
    (203.15, (255, 40, 0)),  # -70 C
    (213.15, (255, 230, 0)),  # -60 C
    (223.15, (0, 190, 70)),  # -50 C
    (233.15, (0, 80, 220)),  # -40 C
    (243.15, (110, 190, 255)),  # -30 C  end of the colour scale
    (243.16, (215, 215, 215)),  # start of the grey scale
    (313.15, (8, 8, 8)),  # +40 C  hot ground
]


def _to_bytes(rgb01: np.ndarray) -> np.ndarray:
    """0..1 float (NaN = missing) -> uint8 with data in 1..255 and missing as RGB_FILL."""
    scaled = rgb01 * 255
    return np.where(np.isnan(scaled), RGB_FILL, np.clip(np.round(scaled), 1, 255)).astype(RGB_DTYPE)


def true_color(arr: np.ndarray, variables: list[str]) -> np.ndarray:
    """CIMSS natural true-colour RGB from ABI C01/C02/C03 reflectances.

    ABI has no green band; the CIMSS recipe synthesises one as
    0.45 red + 0.10 veggie (0.86 um) + 0.45 blue. Each band is clipped to 0..1 and
    gamma-stretched (1/2.2). Takes a (..., variable, y, x) rollout step and returns
    (..., y, x, rgb) uint8 as stored; NaN (outside the GOES view or the region) -> 0.
    """
    red, veggie, blue = (arr[..., list(variables).index(ch), :, :] for ch in TRUE_COLOR_CHANNELS)
    green = 0.45 * red + 0.10 * veggie + 0.45 * blue
    rgb = np.stack([red, green, blue], axis=-1)
    rgb = np.clip(rgb, 0, 1) ** (1 / TRUE_COLOR_GAMMA)
    return _to_bytes(rgb)


def clean_ir(arr: np.ndarray, variables: list[str]) -> np.ndarray:
    """Colour-enhanced Clean IR (C13, 10.35 um) composite, for night-time viewing.

    Brightness temperature (K) through `CLEAN_IR_TABLE`. Same (..., variable, y, x) ->
    (..., y, x, rgb) uint8 contract as `true_color`.
    """
    bt = arr[..., list(variables).index(CLEAN_IR_CHANNEL), :, :]
    temps = np.array([t for t, _ in CLEAN_IR_TABLE])
    colours = np.array([c for _, c in CLEAN_IR_TABLE], dtype="float64") / 255
    rgb = np.stack([np.interp(bt, temps, colours[:, i]) for i in range(3)], axis=-1)
    rgb[np.isnan(bt)] = np.nan
    return _to_bytes(rgb)


COMPOSITES = {"true_color": true_color, "clean_ir": clean_ir}
COMPOSITE_ATTRS = {
    "true_color": {
        "long_name": "CIMSS natural true-colour RGB composite (ABI C02 / synthetic green / "
        "C01 reflectance, gamma 2.2), 0-255",
        "source_channels": " ".join(TRUE_COLOR_CHANNELS),
    },
    "clean_ir": {
        "long_name": "colour-enhanced Clean IR (ABI C13 10.35 um brightness temperature; "
        "grey above -30 C, colour scale for colder cloud tops), 0-255",
        "source_channels": CLEAN_IR_CHANNEL,
    },
}


# ============================================================================
# GOES FRESHNESS (pure python + obstore listing)
# ============================================================================
GOES_SATELLITE = "goes19"  # GOES-East, operational since 2025-04-07
GOES_SCAN_MODE = "C"  # CONUS sector, one scan every 5 min
SLOT_STEP = timedelta(minutes=10)  # model step, and the cadence of inits
SEARCH_LOOKBACK = timedelta(hours=2)  # how far back to hunt for a complete input window
REALTIME_LAG = timedelta(minutes=30)  # blind fallback when the bucket cannot be listed
# A slot is "available" once its MCMIPC file is listed in the bucket, so no fixed lag is
# needed: the CONUS scan for slot hh:m0 starts ~hh:m1:17 and is on AWS a few minutes
# later. --min-lag can hold runs back further (minutes).
MIN_LAG = timedelta(minutes=0)
# OR_ABI-L2-MCMIPC-M6_G19_s20263201801172_e..._c....nc -> scan start
_SCAN_START = re.compile(r"_s(\d{4})(\d{3})(\d{2})(\d{2})(\d{2})\d")


def scan_start(path: str) -> datetime:
    """Scan start time (UTC) encoded in an ABI L2 file name."""
    m = _SCAN_START.search(path.rsplit("/", 1)[-1])
    if m is None:
        raise ValueError(f"no scan start in {path!r}")
    year, doy, hh, mm, ss = (int(g) for g in m.groups())
    return datetime(year, 1, 1, hh, mm, ss, tzinfo=UTC) + timedelta(days=doy - 1)


def floor_to_slot(when: datetime, step: timedelta = SLOT_STEP) -> datetime:
    """Round `when` down onto the `step` grid (anchored at midnight UTC)."""
    when = when.astimezone(UTC) if when.tzinfo else when.replace(tzinfo=UTC)
    midnight = when.replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight + ((when - midnight) // step) * step


def scan_slot(start: datetime) -> datetime:
    """The 5-min slot a CONUS scan belongs to: its start time rounded to the nearest 5 min.

    This mirrors `GOES._get_s3_path`, which serves the file whose start is closest to
    the requested time (scan for slot hh:00 starts at ~hh:01:17).
    """
    return floor_to_slot(start + timedelta(minutes=2.5), timedelta(minutes=5))


def latest_complete_slot(
    slots: set[datetime], n_frames: int, frame_step: timedelta, not_after: datetime
) -> datetime:
    """Newest 10-min slot <= `not_after` whose `n_frames` input frames are all present."""
    for slot in sorted(slots, reverse=True):
        if slot > not_after or slot != floor_to_slot(slot):
            continue
        if all(slot - i * frame_step in slots for i in range(n_frames)):
            return slot
    raise FileNotFoundError(
        f"no {n_frames} consecutive {frame_step} slots up to {not_after:%H:%M} "
        f"({len(slots)} scans listed)"
    )


def list_goes_slots(now: datetime, lookback: timedelta = SEARCH_LOOKBACK) -> set[datetime]:
    """Slots of every MCMIPC file listed in the bucket over the last `lookback`.

    Lists hour directories directly instead of `GOES.available`, which reports any hour
    with a file in it as available -- and `fetch_data` would then silently serve the
    closest older scan for a slot that is not published yet.
    """
    from earth2studio.data.goes import GOES
    from earth2studio.data.utils import obstore_store_from_url

    store = obstore_store_from_url(f"s3://noaa-{GOES_SATELLITE}")
    slots = set()
    hour = (now - lookback).replace(minute=0, second=0, microsecond=0)
    while hour <= now:
        prefix = GOES.BASE_URL.format(
            satellite=GOES_SATELLITE,
            scan_mode=GOES_SCAN_MODE,
            year=hour.year,
            day_of_year=hour.timetuple().tm_yday,
            hour=hour.hour,
        ).split(f"noaa-{GOES_SATELLITE}/", 1)[1]
        for chunk in store.list(prefix=prefix):
            for entry in chunk:
                if f"MCMIP{GOES_SCAN_MODE}" in entry["path"]:
                    slots.add(scan_slot(scan_start(entry["path"])))
        hour += timedelta(hours=1)
    return slots


def latest_goes_slot(n_frames: int, frame_step: timedelta, min_lag: timedelta = MIN_LAG):
    """Freshest init whose whole input window is listed in the bucket."""
    now = datetime.now(UTC)
    return latest_complete_slot(list_goes_slots(now), n_frames, frame_step, now - min_lag)


def resolve_start_time(
    pinned: np.datetime64 | None,
    n_frames: int,
    frame_step: timedelta,
    min_lag: timedelta = MIN_LAG,
) -> datetime:
    """The analysis time to run: pinned, else latest available, else `REALTIME_LAG` back."""
    if pinned is not None:
        return floor_to_slot(pinned.astype("datetime64[s]").astype(datetime).replace(tzinfo=UTC))
    try:
        return latest_goes_slot(n_frames, frame_step, min_lag=min_lag)
    except Exception as err:  # no network, feed gap beyond the lookback
        fallback = floor_to_slot(datetime.now(UTC) - REALTIME_LAG)
        print(f"GOES bucket listing failed ({err!r}); falling back to {REALTIME_LAG} back")
        return fallback


# ============================================================================
# STORE LAYOUT
# ============================================================================
# 512 x 896 spatial chunks: 2 x 2 per frame of a ~1024 x 1792 CONUS grid, ~1.4 MB (uint8)
# per composite chunk. `rgb` stays unsplit, so a chunk holds all three bands.
CHUNKS = {"ensemble": 1, "time": 1, "lead_time": 1, "y": 512, "x": 896}
# `time`/`valid_time` hold a few bytes per init; 4096 inits (~4 weeks) fit one chunk.
COORD_TIME_CHUNK = 4096

# GeoZarr `proj` and `spatial` conventions (https://geozarr.org/conventions.html).
ZARR_CONVENTIONS = [
    {
        "schema_url": "https://raw.githubusercontent.com/zarr-conventions/proj/refs/tags/v0.1/schema.json",
        "spec_url": "https://github.com/zarr-conventions/proj/blob/v0.1/README.md",
        "uuid": "f17cb550-5864-4468-aeb7-f3180cfb622f",
        "name": "proj",
        "description": "Coordinate reference system information for geospatial data",
    },
    {
        "schema_url": "https://raw.githubusercontent.com/zarr-conventions/spatial/refs/tags/v0.1/schema.json",
        "spec_url": "https://github.com/zarr-conventions/spatial/blob/v0.1/README.md",
        "uuid": "689b58e2-cf7b-45e0-9fff-9cfc0883d6b4",
        "name": "spatial",
        "description": "Spatial coordinate information",
    },
]

# `grid_mapping` is what the Flux tiles service projects with; `coordinates` makes
# `xr.open_zarr` read lat/lon/valid_time back as coordinates of every field.
GEOREF = {"coordinates": "lat lon valid_time", "grid_mapping": GRID_MAPPING}
PUBLISH_TARGETS = ["local", "arraylake"]
# Default --publish-target arraylake destination; the cube goes in its root group.
ARRAYLAKE_REPO = "nvidia/sc26-chicago-stormscope_us-booth"
MODEL_NAME = "3km_10min_flash"
REGION_PADDING = 25  # real context pixels per side for --region (set_domain)


def geozarr_attrs(y, x) -> dict:
    """GeoZarr `proj` + `spatial` attributes for a group over this `(y, x)` grid (metres).

    Origin is the corner of pixel (0, 0); `y` runs south to north, so the transform is
    south-up (`e > 0`).
    """
    y_m = np.asarray(y, dtype="float64")
    x_m = np.asarray(x, dtype="float64")
    dy, dx = y_m[1] - y_m[0], x_m[1] - x_m[0]
    if not (np.allclose(np.diff(y_m), dy) and np.allclose(np.diff(x_m), dx)):
        raise ValueError("y/x are not evenly spaced; no affine transform describes them")
    x0, y0 = x_m[0] - dx / 2, y_m[0] - dy / 2
    x1, y1 = x0 + dx * len(x_m), y0 + dy * len(y_m)
    return {
        "zarr_conventions": ZARR_CONVENTIONS,
        "proj:wkt2": HRRR_CRS.to_wkt(),
        "proj:projjson": HRRR_CRS.to_json_dict(),
        "spatial:dimensions": ["y", "x"],
        "spatial:shape": [len(y_m), len(x_m)],
        "spatial:transform": [float(dx), 0.0, float(x0), 0.0, float(dy), float(y0)],
        "spatial:bbox": [
            float(min(x0, x1)),
            float(min(y0, y1)),
            float(max(x0, x1)),
            float(max(y0, y1)),
        ],
        "spatial:registration": "pixel",
    }


def parse_region(text: str | None) -> tuple[float, float, float, float] | None:
    """`lat_min,lat_max,lon_min,lon_max` (degrees, west negative) -> tuple, or None."""
    if text is None or text.strip().lower() in ("", "conus", "none"):
        return None
    parts = [float(v) for v in text.split(",")]
    if len(parts) != 4:
        raise ValueError("--region needs lat_min,lat_max,lon_min,lon_max")
    lat_min, lat_max, lon_min, lon_max = parts
    if not (lat_min < lat_max and lon_min < lon_max):
        raise ValueError("--region needs lat_min < lat_max and lon_min < lon_max")
    return lat_min, lat_max, lon_min, lon_max


def parse_args() -> argparse.Namespace:
    """Parse and validate the CLI flags.

    `--start-time` comes back as a `np.datetime64` (or None). `--publish-target` falls
    back to `STORMSCOPE_PUBLISH_TARGET`, then "local"; the Arraylake repo and token are
    checked here so a misconfigured run fails before the model is loaded.
    """
    p = argparse.ArgumentParser(
        description="StormScope US nowcast: fetch GOES-19 ABI CONUS -> Earth2Studio rollout "
        "-> streaming Icechunk/Arraylake publish",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--start-time",
        default=None,
        help="initial-condition time, ISO 8601 UTC on a 10-min boundary (e.g. "
        "2026-11-16T18:00). Default: the freshest slot whose input window is in the "
        "noaa-goes19 bucket, falling back to REALTIME_LAG behind now if it can't be listed.",
    )
    p.add_argument(
        "--min-lag",
        type=float,
        default=MIN_LAG.total_seconds() / 60,
        help="minutes a slot must be past its slot time before it is considered",
    )
    p.add_argument(
        "--wait-seconds",
        type=float,
        default=15,
        help="seconds to sleep before looking again when no new init is available or a pass failed",
    )
    p.add_argument("--n-steps", type=int, default=12, help="forecast steps of 10 min (12 = 2 h)")
    p.add_argument(
        "--region",
        default=os.environ.get("STORMSCOPE_REGION"),
        help="lat_min,lat_max,lon_min,lon_max box (west negative) to run instead of full "
        "CONUS [env: STORMSCOPE_REGION, default full CONUS]",
    )
    p.add_argument("--output-dir", default="outputs", help="where the local Icechunk store goes")
    p.add_argument(
        "--publish-target",
        choices=PUBLISH_TARGETS,
        default=None,
        help="local = Icechunk repo on disk, arraylake = hosted repo (needs ARRAYLAKE_API_TOKEN) "
        "[env: STORMSCOPE_PUBLISH_TARGET, default local]",
    )
    p.add_argument(
        "--arraylake-repo",
        default=os.environ.get("ARRAYLAKE_REPO", ARRAYLAKE_REPO),
        help="Arraylake org/repo when --publish-target arraylake [env: ARRAYLAKE_REPO]",
    )
    p.add_argument("--device", choices=["auto", "cuda", "cpu"], default="auto")
    args = p.parse_args()

    if args.n_steps < 1:
        p.error("--n-steps must be >= 1")
    if args.min_lag < 0:
        p.error("--min-lag must be >= 0")
    args.min_lag = timedelta(minutes=args.min_lag)
    if args.wait_seconds < 0:
        p.error("--wait-seconds must be >= 0")
    try:
        args.region = parse_region(args.region)
    except ValueError as err:
        p.error(str(err))
    if args.start_time is not None:
        try:
            args.start_time = np.datetime64(args.start_time)
        except ValueError:
            p.error(f"--start-time {args.start_time!r} is not an ISO 8601 timestamp")
        if np.isnat(args.start_time):
            p.error("--start-time must be a real timestamp")
        if args.start_time != np.datetime64(args.start_time, "10m"):
            p.error(f"--start-time {args.start_time} must be on a 10-min boundary")
    if args.publish_target is None:
        # argparse does not check `choices` against an env-derived default
        args.publish_target = os.environ.get("STORMSCOPE_PUBLISH_TARGET", "local")
        if args.publish_target not in PUBLISH_TARGETS:
            p.error(
                f"STORMSCOPE_PUBLISH_TARGET={args.publish_target!r} must be one of {PUBLISH_TARGETS}"
            )
    if args.publish_target == "arraylake":
        if not args.arraylake_repo:
            p.error("--publish-target arraylake needs --arraylake-repo or ARRAYLAKE_REPO")
        if not os.environ.get("ARRAYLAKE_API_TOKEN"):
            p.error("--publish-target arraylake needs ARRAYLAKE_API_TOKEN in the environment")
    return args


# ============================================================================
# MODEL + IO (heavy imports deferred so the composites/freshness helpers above
# import without torch / earth2studio, e.g. in tests)
# ============================================================================
def _heavy_imports():
    global torch, icechunk, earth2studio, IceChunkBackend, fetch_data, GOES
    global StormScopeBase, StormScopeGOES, BloscCodec, ZstdCodec, tqdm
    import earth2studio
    import icechunk
    import torch
    from earth2studio.data import GOES, fetch_data
    from earth2studio.io import IceChunkBackend
    from earth2studio.models.px.stormscope import StormScopeBase, StormScopeGOES
    from tqdm import tqdm
    from zarr.codecs import BloscCodec, ZstdCodec


def load_model(device, region):
    """Load StormScopeGOES `3km_10min_flash`, optionally restricted to `region`."""
    package = StormScopeBase.load_default_package()
    model = StormScopeGOES.load_model(
        package=package,
        model_name=MODEL_NAME,
        conditioning_data_source=None,
        amp=True,
        compile=True,
    )
    model = model.to(device)
    model.eval()
    if region is not None:
        model = model.set_domain(*region, padding=REGION_PADDING)
    goes_lat, goes_lon = GOES.grid(satellite=GOES_SATELLITE, scan_mode=GOES_SCAN_MODE)
    model.build_input_interpolator(goes_lat, goes_lon)
    return model


def output_grid(model) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """(y, x, lat, lon) of the stored cube: the model grid, cropped to the region if any.

    lon is converted from the model's 0..360 to -180..180.
    """
    y, x = np.asarray(model.y), np.asarray(model.x)
    lat = model.latitudes.detach().cpu().numpy()
    lon = model.longitudes.detach().cpu().numpy()
    region_info = getattr(model, "region_info", None)
    if region_info is not None:
        ys, xs = region_info.output_slices
        y, x, lat, lon = y[ys], x[xs], lat[ys, xs], lon[ys, xs]
    lon = (lon + 180.0) % 360.0 - 180.0
    return y, x, lat.astype("float32"), lon.astype("float32")


def fetch_initial_condition(model, goes, start_time: np.datetime64, device):
    """Fetch the GOES input window ending at `start_time` (raw GOES grid; the model
    interpolates onto its own grid in `prep_input`)."""
    in_coords = model.input_coords()
    x, coords = fetch_data(
        goes,
        time=np.array([start_time]),
        variable=np.array(in_coords["variable"]),
        lead_time=in_coords["lead_time"],
        device=device,
    )
    return x.to(dtype=torch.float32), coords


def add_ensemble_dim(x, coords: dict, ensemble_size: int):
    """Expand to (ensemble, time, lead_time, variable, ...)."""
    x = x.unsqueeze(0).expand(ensemble_size, *x.shape)
    coords = OrderedDict(coords)
    coords["ensemble"] = np.arange(ensemble_size)
    coords.move_to_end("ensemble", last=False)
    return x, coords


def add_coord(backend, name, values, dims, attrs=None, dtype=None, compressors=None) -> None:
    """Write a non-dimension coordinate, e.g. 2-D `lat`/`lon` over `(y, x)`.

    `IceChunkBackend.add_array` would take an n-dimensional entry for the grid itself
    and replace it with enumerated index dimensions.
    """
    values = np.asarray(values, dtype=dtype)
    chunks = tuple(
        CHUNKS[dim] if dim in ("y", "x") else COORD_TIME_CHUNK if dim == "time" else size
        for dim, size in zip(dims, values.shape, strict=True)
    )
    if name not in backend.root:
        array = backend.root.create_array(
            name,
            shape=values.shape,
            chunks=chunks,
            dtype=values.dtype,
            dimension_names=list(dims),
            compressors=compressors or backend.zarr_codecs,
        )
        array[:] = values
    if attrs:
        backend.root[name].attrs.update(attrs)


def add_grid_mapping(backend, name: str, attrs: dict) -> None:
    """Write a CF grid mapping variable: a scalar whose attributes describe the CRS."""
    if name not in backend.root:
        array = backend.root.create_array(
            name, shape=(), dtype="int32", fill_value=0, dimension_names=()
        )
        array[...] = 0
    backend.root[name].attrs.update(attrs)


def step_composites(model, x_pred, coords_pred: OrderedDict, channels: list[str]):
    """One rollout step -> the `(tensors, coords, names)` to hand `write`.

    Crops to the requested region (a no-op for full CONUS) and computes both
    composites. `copy=True` because the generator keeps writing into its own buffers
    between yields, and the non-blocking store write may still be reading.
    """
    x_out, coords_out = model.crop_output(x_pred, coords_pred)
    arr = x_out.detach().to("cpu", torch.float32, copy=True).numpy()
    rgb_coords = OrderedDict((d, v) for d, v in coords_out.items() if d != "variable")
    rgb_coords["rgb"] = RGB_VALUES
    names = list(COMPOSITES)
    return (
        [torch.from_numpy(COMPOSITES[name](arr, channels)) for name in names],
        rgb_coords,
        names,
    )


def build_backend(publish_target: str, output_dir: str, arraylake_repo: str):
    """Open the Icechunk store to publish into, keeping earlier runs. Returns (backend, location)."""

    if publish_target == "arraylake":
        import arraylake

        client = arraylake.Client(token=os.environ["ARRAYLAKE_API_TOKEN"])
        storage, location = client.get_icechunk_storage(arraylake_repo), arraylake_repo
    else:
        storage = location = os.path.join(output_dir, "stormscope_us.icechunk")
    backend = IceChunkBackend(storage, chunks=CHUNKS, zarr_codecs=[ZstdCodec(level=3)])
    return backend, location


def create_schema(backend, model, coords, lead_time: np.ndarray, region) -> None:
    """Allocate the cube in an empty repo, sized for this run's init alone.

    `lead_time` runs from 0 -- the observed analysis frame -- to n_steps * 10 min. Later
    runs grow `time` by their own init (see `extend_schema`).
    """
    y, x, lat, lon = output_grid(model)
    total_coords = OrderedDict(
        ensemble=coords["ensemble"], time=coords["time"], lead_time=lead_time, y=y, x=x
    )
    rgb_coords = OrderedDict(**total_coords, rgb=RGB_VALUES)

    # `time` first, so `add_array` skips it rather than chunking it at this run's length.
    add_coord(backend, "time", total_coords["time"], ("time",))
    backend.coords["time"] = total_coords["time"]
    backend.add_array(rgb_coords, [])  # other coordinate arrays only
    # Created directly: `add_array` takes its dtype from initial data only, and passing
    # data would write every chunk of the cube.
    for name in COMPOSITES:
        backend.root.create_array(
            name,
            shape=[len(values) for values in rgb_coords.values()],
            chunks=[backend.chunks.get(dim, len(values)) for dim, values in rgb_coords.items()],
            dtype=RGB_DTYPE,
            fill_value=RGB_FILL,
            dimension_names=list(rgb_coords),
            compressors=backend.zarr_codecs,
        )
        backend.root[name].attrs.update({**GEOREF, **RGB_ENCODING, **COMPOSITE_ATTRS[name]})
    backend.root["rgb"].attrs.update(RGB_BAND_ATTRS)
    latlon_codec = [BloscCodec(cname="zstd", clevel=3, shuffle="shuffle")]
    add_coord(
        backend,
        "lat",
        lat,
        ("y", "x"),
        {"standard_name": "latitude", "units": "degrees_north"},
        compressors=latlon_codec,
    )
    add_coord(
        backend,
        "lon",
        lon,
        ("y", "x"),
        {"standard_name": "longitude", "units": "degrees_east"},
        compressors=latlon_codec,
    )
    add_grid_mapping(backend, GRID_MAPPING, HRRR_LCC)
    for dim, axis in (("x", "X"), ("y", "Y")):
        backend.root[dim].attrs.update(
            {
                "standard_name": f"projection_{dim}_coordinate",
                "units": "m",
                "axis": axis,
                "long_name": f"HRRR Lambert conformal {dim}-coordinate",
            }
        )
    add_coord(
        backend,
        "valid_time",
        total_coords["time"][:, None] + total_coords["lead_time"][None, :],
        ("time", "lead_time"),
        {"standard_name": "time", "long_name": "valid time (time + lead_time)"},
    )
    backend.root["time"].attrs.update(
        {
            "standard_name": "forecast_reference_time",
            "long_name": "analysis (nowcast initialisation) time",
        }
    )
    backend.root["lead_time"].attrs.update(
        {
            "standard_name": "forecast_period",
            "long_name": "offset from analysis time; 0 = observed analysis frame, > 0 = "
            "forecast. Earlier observed frames are model input and are not stored.",
        }
    )
    backend.root["ensemble"].attrs.update(
        {"standard_name": "realization", "long_name": "ensemble member"}
    )
    backend.root.attrs.update(
        {
            "title": "StormScope-US nowcast on GOES-19 ABI CONUS",
            "model": f"StormScopeGOES {MODEL_NAME}",
            "satellite": GOES_SATELLITE,
            "earth2studio_version": earth2studio.__version__,
            "region": "CONUS" if region is None else ",".join(str(v) for v in region),
            **geozarr_attrs(y, x),
        }
    )


TIME_ARRAYS = ("time", "valid_time", *COMPOSITES)


def extend_schema(backend, time_: np.ndarray, lead_time: np.ndarray, y: np.ndarray) -> None:
    """Append this run's init to `time` in an existing cube, uncommitted.

    The rollout steps then fill the new `time` slice in the same session, and one
    commit publishes both. An init already in `time` is a rerun: its slice is
    overwritten in place.
    """
    for name in COMPOSITES:
        if name not in backend.root or backend.root[name].dtype != RGB_DTYPE:
            raise ValueError(f"repo has no {RGB_DTYPE} {name}; publish to an empty repo or branch")
    stored_lead = backend.root["lead_time"][:]
    if not np.array_equal(stored_lead, lead_time):
        raise ValueError(
            f"repo has {len(stored_lead)} lead times (--n-steps {len(stored_lead) - 1}), this "
            f"run has {len(lead_time)} (--n-steps {len(lead_time) - 1}); rerun with the repo's --n-steps"
        )
    if not np.array_equal(backend.root["y"][:], y):
        raise ValueError("repo grid differs from this run's (--region changed?); use another repo")
    init = np.datetime_as_string(time_[0], unit="m")
    stored_time = backend.coords["time"]
    if np.isin(time_, stored_time).all():
        print(f"init {init} already in repo; overwriting its slice")
        return

    n = len(stored_time)
    for name in TIME_ARRAYS:
        array = backend.root[name]
        shape = list(array.shape)
        shape[array.metadata.dimension_names.index("time")] += len(time_)
        array.resize(tuple(shape))
    backend.root["time"][n:] = time_
    backend.root["valid_time"][n:] = time_[:, None] + lead_time[None, :]
    # `write` locates slices through this in-memory copy, which is read once at open.
    backend.coords["time"] = np.concatenate([stored_time, time_])


class StormScopeUSPipeline:
    """StormScope-US loaded once, run on any number of inits."""

    def __init__(self, device="auto", region=None):
        _heavy_imports()
        if device == "auto":
            self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        else:
            self.device = torch.device(device)
        self.region = region
        self.model = load_model(self.device, region)
        self.goes = GOES(satellite=GOES_SATELLITE, scan_mode=GOES_SCAN_MODE)

    @property
    def n_frames(self) -> int:
        return len(self.model.input_coords()["lead_time"])

    @property
    def frame_step(self) -> timedelta:
        lead = self.model.input_coords()["lead_time"]
        step = lead[1] - lead[0] if len(lead) > 1 else self.model.output_times[0]
        return timedelta(seconds=int(step / np.timedelta64(1, "s")))

    def __call__(self, start_time, n_steps, publish_target, output_dir, arraylake_repo):
        """Run one nowcast from `start_time` and publish it in one commit."""
        os.makedirs(output_dir, exist_ok=True)
        t0 = time.monotonic()

        with torch.no_grad():
            x, coords = fetch_initial_condition(self.model, self.goes, start_time, self.device)
            x, coords = add_ensemble_dim(x, coords, ensemble_size=1)
        t_fetch = time.monotonic() - t0
        channels = [str(v) for v in self.model.variables]

        backend, location = build_backend(publish_target, output_dir, arraylake_repo)
        lead_time = np.arange(n_steps + 1) * self.model.output_times[0]
        init = np.datetime_as_string(coords["time"][0], unit="m")
        if "true_color" not in backend.root:
            create_schema(backend, self.model, coords, lead_time, self.region)
        else:
            extend_schema(backend, coords["time"], lead_time, output_grid(self.model)[0])

        for step, (x_pred, coords_pred) in enumerate(
            tqdm(self.model.create_iterator(x, coords), total=n_steps + 1)
        ):
            # Non-blocking: the backend's thread pool uploads while the GPU computes.
            backend.write(*step_composites(self.model, x_pred, coords_pred, channels))
            if step == n_steps:
                break
        t_roll = time.monotonic() - t0 - t_fetch

        message = f"stormscope-us {init} lead 0-{int(lead_time[-1] / np.timedelta64(1, 'm'))} min"
        snapshot = backend.commit(
            message,
            metadata={"time": init, "status": "ingested"},
            rebase_with=icechunk.ConflictDetector(),
        )
        t_total = time.monotonic() - t0
        print(f"{message} -> {snapshot}")
        print(
            f"timing: fetch {t_fetch:.1f}s, rollout+write {t_roll:.1f}s, "
            f"commit {t_total - t_fetch - t_roll:.1f}s, total {t_total:.1f}s"
        )
        print(f"Published to {publish_target} ({location})")


def main():
    """Load the model once, then run every new init as it becomes available."""
    from dotenv import load_dotenv

    load_dotenv()
    args = parse_args()
    pipeline = StormScopeUSPipeline(device=args.device, region=args.region)

    last_start = None
    while True:
        try:
            analysis_time = resolve_start_time(
                args.start_time, pipeline.n_frames, pipeline.frame_step, args.min_lag
            )
            lag_min = (datetime.now(UTC) - analysis_time).total_seconds() / 60
            print(
                f"analysis time {analysis_time:%Y-%m-%d %H:%M} UTC ({lag_min:.0f} min behind now)"
            )
            start_time = np.datetime64(analysis_time.replace(tzinfo=None))
            if start_time == last_start:
                time.sleep(args.wait_seconds)
                continue

            pipeline(
                start_time=start_time,
                n_steps=args.n_steps,
                publish_target=args.publish_target,
                output_dir=args.output_dir,
                arraylake_repo=args.arraylake_repo,
            )
            last_start = start_time
        except Exception as e:
            print(
                f"{datetime.now()}: Exception occurred: {e!r}, retrying after {args.wait_seconds} s"
            )
            time.sleep(args.wait_seconds)

        if args.start_time is not None:
            break  # run only one if start_time is fixed


if __name__ == "__main__":
    main()
