# sc26-chicago-stormscope_us-booth

StormScope-US nowcasting on GOES-19 ABI over the contiguous US, streamed into Arraylake --
the booth demo for SC26 Chicago (McCormick Place, 15–20 November 2026). The deployed
pipeline goes offline after the event.

## Links

- Earth2Studio example: https://nvidia.github.io/earth2studio/main/examples/04_nowcasting/03_stormscope_goes_example/
- Arraylake repo: https://app.earthmover.io/nvidia/sc26-chicago-stormscope_us-booth
- Hosted presentation: https://nvidia-sc26-chicago.earthmover.io/
- Mobile viewer: https://nvidia-sc26-chicago-viewer.earthmover.io/

[`scripts/stormscope_us_pipeline.py`](scripts/stormscope_us_pipeline.py) runs
`StormScopeGOES` (`3km_10min_flash`, earth2studio 0.20.0) end to end: find the newest
10-minute slot whose six input frames (`T`-50 … `T`) are on NOAA's public `noaa-goes19`
bucket, roll the model forward autoregressively in 10-minute steps on the 3 km HRRR grid,
and write each step to Icechunk on Arraylake as it is produced. GOES-19 files are on S3
about 4.3 min after their slot time and need no credentials, so the pipeline runs a few
minutes behind real time. No MRMS radar. See [Pipeline script](#pipeline-script) and
[docs/END2END_NEARREALTIME_PERFORMANCE.md](docs/END2END_NEARREALTIME_PERFORMANCE.md).

## Deployments

| | Runs as | Live SQL | Audience | URL |
|---|---|---|---|---|
| **Booth presentation** ([`presentation/`](presentation/)) | `uv run presentation/server.py` on the booth machine, full screen on the TV | editable | SC26 visitors | `http://localhost:8000` on the booth machine |
| **Hosted presentation** ([`presentation/`](presentation/)) | Vercel project `sc26-chicago-stormscope-us-booth`, root directory `presentation` | fixed: the venue queries only, cached per init | internal sharing, unlisted URL | `nvidia-sc26-chicago.earthmover.io` |
| **Mobile site** ([`site/`](site/)) | Vercel project `sc26-chicago-stormscope-us-booth-site`, root directory `site`, static | none | phones, via the booth QR code | `nvidia-sc26-chicago-viewer.earthmover.io` |

The domains follow the GTC Berlin pattern. The Vercel project names use hyphens only, so
the `*.vercel.app` fallback domains are not truncated.

Both presentation deployments serve the same `presentation/web/` page and the same logic in
`presentation/booth.py`. The difference is the `sql_editable` flag in `/api/config`:
`server.py` answers `true`, the Vercel functions in `presentation/api/` answer `false`.

## Viz

Tiles come from a public Arraylake tiles service in the `nvidia` org
(`tiles-dd7cd36ec0562874.compute.arraylake.app`, set as `tile_base`). Public, because the booth screen and phones fetch
tiles straight from the browser, which can't attach an `Authorization` header; rendered
tiles are reachable by anyone holding the URL, the underlying chunks stay private. Run it
in us-east-1 next to the data, with replicas pinned during booth hours:

```
al compute enable nvidia tiles --sku-code s --is-public
al compute update nvidia <tiles-id> --min-replicas 8 --max-replicas 8
```

Set `--min-replicas 0` after booth hours and `al compute disable` after the event.

Render parameters for `true_color`, `clean_ir` and `water_vapor`:

| Parameter | Value | Why |
| --- | --- | --- |
| `style` | `raster/rgb` | Real 3-band composite; pass `variables=true_color` with no `rgb` selector. |
| `colorscalerange` | `0,255` | All three composites are stored as uint8 0–255 (see [Pipeline script](#pipeline-script)). |
| `lead_time` | `PT10M` | 13 frames: 0, 10, …, 120 minutes. 0 is the observed satellite frame, the rest forecast. |
| `ensemble` | `0` | Single member; required because every variable is 5-D. |

`true_color` is black on the night side; use `clean_ir` there (the booth page and the
viewer pick it automatically while it is dark at the venue). `water_vapor` works day and
night too; it shows moist and dry air rather than cloud-top temperature.

## Running it

The model needs a CUDA GPU. Install the GPU extra there (`uv sync --extra gpu`, with
NATTEN's prebuilt wheels from <https://whl.natten.org/>; it also builds `earth2grid`) and
run the [pipeline script](#pipeline-script).

Credentials come from a local `.env` (see [`.env.example`](.env.example)):

- `ARRAYLAKE_API_TOKEN` -- ingest target. GOES-19 data is public.

Each init is one commit, made after its last step, so stopping a run partway publishes
nothing. Rerunning the same init overwrites its slice.

### Docker

On a cloud GPU instance (us-east-1, next to `noaa-goes19` and the Arraylake bucket),
[`compose.yaml`](compose.yaml) runs the pipeline in a container built from
[`Dockerfile`](Dockerfile): the NGC PhysicsNeMo 26.08 image plus earth2studio 0.20.0,
NATTEN and earth2grid. The container starts the script with no arguments, so it runs
continuously, publishing each new init to Arraylake, and restarts unless stopped. The host
needs the NVIDIA Container Toolkit, and pulling from `nvcr.io` may need an NGC login.

```bash
mkdir -p secrets
printf %s "<token>" > secrets/arraylake_api_token
docker compose up -d --build
docker compose logs -f
```

`STORMSCOPE_PUBLISH_TARGET`, `ARRAYLAKE_REPO` and `STORMSCOPE_REGION` can be overridden
from the shell or a `.env` next to `compose.yaml`. Arguments after the service name replace
the default command, e.g. a single pinned run:

```bash
docker compose run --rm pipeline python scripts/stormscope_us_pipeline.py --start-time 2026-11-16T18:00
```

The model checkpoint and downloaded GOES files persist in the `cache` volume.

## Pipeline script

```
GOES-19 ABI CONUS (noaa-goes19) → Earth2Studio StormScopeGOES Flash → Icechunk/Arraylake publish → tile dashboard
```

It searches for the freshest complete input window by listing the bucket (`GOES.available`
is not enough: it reports any hour with a file in it, and `fetch_data` would then silently
serve the closest older scan), makes one commit per init, and uploads steps in the
background while the next one is computed. It publishes through plain
`earth2studio.io.IceChunkBackend` with `arraylake.Client.get_icechunk_storage` to the root
group of `nvidia/sc26-chicago-stormscope_us-booth`. Each run extends the schema by its init
time and appends along `time` in that same commit; every run must therefore use the same
`--n-steps` and `--region`.

```bash
uv run python scripts/stormscope_us_pipeline.py --n-steps 3                    # local Icechunk in outputs/
uv run python scripts/stormscope_us_pipeline.py --start-time 2026-11-16T18:00 --n-steps 12
uv run python scripts/stormscope_us_pipeline.py --region 36,46,-96,-82          # Midwest box only
uv run python scripts/stormscope_us_pipeline.py --publish-target arraylake
```

| Flag | Default | Notes |
|---|---|---|
| `--start-time` | freshest slot with all 6 input frames listed | ISO 8601 UTC on a 10-min boundary. If the bucket can't be listed, falls back to 30 min behind now. |
| `--min-lag` | `0` | minutes a slot must be past its slot time to be considered |
| `--wait-seconds` | `15` | sleep before looking again when there is no new init or a pass failed |
| `--n-steps` | `12` | 10-min steps |
| `--region` | `$STORMSCOPE_REGION` or full CONUS | `lat_min,lat_max,lon_min,lon_max` (west negative); Flash `set_domain` with 25 px context, stored cropped |
| `--output-dir` | `outputs` | local Icechunk store |
| `--publish-target` | `$STORMSCOPE_PUBLISH_TARGET` or `local` | `local` \| `arraylake` |
| `--arraylake-repo` | `$ARRAYLAKE_REPO` or `nvidia/sc26-chicago-stormscope_us-booth` | required with `arraylake`, which also needs `ARRAYLAKE_API_TOKEN` |
| `--device` | `auto` | `auto` \| `cuda` \| `cpu` |

It stores two RGB composites, not the 8 raw channels. Both are
`(ensemble, time, lead_time, y, x, rgb)` uint8 in 0–255 on the HRRR Lambert conformal grid
(1024 × 1792 at 3 km for CONUS; `x`/`y` in meters, CF grid mapping
`hrrr_lambert_conformal`, 2-D `lat`/`lon`). Each composite is computed in 0–1, then stored
as `round(x * 255)` clipped to 1–255. Missing pixels (outside the GOES view or the region,
or a step not written yet) are 0, the Zarr `fill_value`; there is no CF `_FillValue`.

- `true_color`: CIMSS natural true color from ABI reflectances. ABI has no green band, so
  green is synthesized:
  ```
  R = C02 (0.64 µm)    G = 0.45·C02 + 0.10·C03 (0.86 µm) + 0.45·C01    B = C01 (0.47 µm)
  ```
  each clipped to 0–1 and put through EUMETSAT's true-color contrast curve, as in the Berlin
  demo (reflectance·255 `[0, 30, 60, 120, 190, 255]` → `[0, 110, 160, 210, 240, 255]`,
  linear in between). No Rayleigh or solar-zenith correction.
- `clean_ir`: C13 (10.35 µm) brightness temperature through a fixed color table: gray from
  +40 °C (near black) to −30 °C (light gray), then color for cold cloud tops: light blue
  −30, blue −40, green −50, yellow −60, red −70, dark red −80, white −90 °C (`CLEAN_IR_TABLE`
  in the script).
- `water_vapor`: CIRA Simple Water Vapor RGB, day and night. Inverted brightness
  temperatures, linear, gamma 1: R = C13 278.96→202.29 K (cloud height), G = C08 (6.19 µm)
  242.67→214.66 K (upper-level moisture), B = C10 (7.34 µm) 261.03→245.12 K (low-to-mid
  moisture). NOAA's Air Mass RGB would need C12 (9.6 µm), which StormScope-US does not predict.
