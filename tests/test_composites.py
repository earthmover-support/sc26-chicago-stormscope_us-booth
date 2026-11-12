"""The torch composites and the precomputed true_color fields against the numpy recipe of #16.

The Rayleigh lookup is replaced by a smooth stand-in, so no pyspectral tables are needed:
the tests check the composition and the caching, not pyspectral itself.
"""

import time

import numpy as np
import pytest

torch = pytest.importorskip("torch")
pytest.importorskip("pyorbital")

H, W = 96, 160
VARIABLES = ["abi01c", "abi02c", "abi03c", "abi08c", "abi10c", "abi13c"]


class FakeRayleigh:
    """Smooth path reflectance (%) in sun zenith, satellite zenith and azimuth difference."""

    calls = 0

    def get_reflectance(self, sunz, satz, azidiff, band):
        FakeRayleigh.calls += 1
        scale = 8.0 if band == "C01" else 3.0
        sec = 1 / np.cos(np.deg2rad(np.clip(sunz, 0, 85))) + 1 / np.cos(np.deg2rad(satz))
        return np.clip(scale * sec / 4 * (1 + 0.1 * np.cos(np.deg2rad(azidiff))), 0, 100)


@pytest.fixture
def mod(pipeline, monkeypatch):
    monkeypatch.setattr(pipeline, "_rayleigh", FakeRayleigh())
    monkeypatch.setattr(pipeline, "torch", torch, raising=False)  # set by _heavy_imports
    return pipeline


@pytest.fixture(scope="module")
def grid():
    """A CONUS-like lat/lon grid; at 22 UTC in November it spans day, terminator and night."""
    lat, lon = np.meshgrid(np.linspace(50, 24, H), np.linspace(-125, -67, W), indexing="ij")
    return lat.astype("float32"), lon.astype("float32")


@pytest.fixture(scope="module")
def step():
    """One (ensemble, time, variable, y, x) step: dark land, bright cloud, NaN outside view."""
    rng = np.random.default_rng(0)
    arr = rng.uniform(0.0, 0.35, (1, 1, len(VARIABLES), H, W)).astype("float32")
    arr[..., 1:3, 20:40, 30:90] = rng.uniform(0.6, 1.1, (2, 20, 60))  # cloud in C02/C03
    arr[..., 3:, :, :] = rng.uniform(200, 290, (3, H, W))  # brightness temperatures
    arr[..., :, :5] = np.nan
    return arr


def reference_true_color(mod, arr, variables, lat, lon, valid_time):
    """`true_color` as merged in #16 (numpy, geometry computed per call)."""
    from pyorbital import astronomy, orbital

    stride = mod.GEOMETRY_STRIDE
    utc = np.datetime64(valid_time, "us").astype(mod.datetime)
    clat = np.asarray(lat, "float64")[::stride, ::stride]
    clon = np.asarray(lon, "float64")[::stride, ::stride]
    sunz = astronomy.sun_zenith_angle(utc, clon, clat)
    suna = np.rad2deg(astronomy.get_alt_az(utc, clon, clat)[1]) % 360
    sata, sat_elev = orbital.get_observer_look(
        mod.GOES_SUBSAT_LON, 0.0, mod.GOES_ALT_KM, utc, clon, clat, np.zeros_like(clon)
    )
    satz = 90.0 - sat_elev
    azidiff = np.abs(suna - sata % 360)
    azidiff = np.where(azidiff > 180, 360 - azidiff, azidiff)
    shape = np.shape(lat)
    path = {
        b: mod._upsample(mod._rayleigh.get_reflectance(sunz, satz, azidiff, b), shape, stride)
        for b in ("C01", "C02")
    }
    sunz = mod._upsample(sunz, shape, stride)

    red, veggie, blue = (
        mod._sunz_corrected(arr[..., variables.index(ch), :, :] * 100, sunz)
        for ch in mod.TRUE_COLOR_CHANNELS
    )
    relax = np.clip(1 - (red - 20) / 80, 0, 1)
    red, blue = red - path["C02"] * relax, blue - path["C01"] * relax
    red, veggie, blue = (mod._sunz_reduced(b, sunz) for b in (red, veggie, blue))
    green = 0.45 * red + 0.10 * veggie + 0.45 * blue
    rgb = np.stack([red, green, blue], axis=-1)
    rgb = np.interp(np.clip(rgb, 0, 100) * 2.55, *mod.TRUE_COLOR_STRETCH) / 255
    scaled = rgb * 255
    return np.where(np.isnan(scaled), 0, np.clip(np.round(scaled), 1, 255)).astype("uint8")


def test_stretch_matches_np_interp(mod):
    x = np.concatenate([np.linspace(0, 255, 10001), mod.TRUE_COLOR_STRETCH[0]]).astype("float32")
    got = mod._stretch(torch.from_numpy(x)).numpy()
    np.testing.assert_allclose(got, np.interp(x, *mod.TRUE_COLOR_STRETCH), atol=1e-4)
    assert mod._stretch(torch.tensor([np.nan, 10.0]))[0].isnan()


@pytest.mark.parametrize("valid_time", ["2026-11-16T18:00", "2026-11-16T22:00"])
def test_true_color_matches_numpy_recipe(mod, grid, step, valid_time):
    lat, lon = grid
    t = np.datetime64(valid_time)
    expected = reference_true_color(mod, step, VARIABLES, lat, lon, t)
    fields = torch.from_numpy(mod.true_color_fields(lat, lon, t))
    got = mod.true_color(torch.from_numpy(step), VARIABLES, fields).numpy()

    assert got.dtype == np.uint8 and got.shape == expected.shape == (1, 1, H, W, 3)
    diff = np.abs(got.astype(int) - expected.astype(int))
    assert diff.max() <= 1  # float32 vs float64 rounding at byte boundaries
    assert (diff == 0).mean() >= 0.999
    assert (got[..., :5, :] == 0).all()  # NaN -> fill


def test_water_vapor_matches_numpy_recipe(mod, step):
    rgb = np.stack(
        [
            (step[..., VARIABLES.index(ch), :, :] - warm) / (cold - warm)
            for ch, warm, cold in mod.WATER_VAPOR_BANDS
        ],
        axis=-1,
    )
    scaled = np.clip(rgb, 0, 1) * 255
    expected = np.where(np.isnan(scaled), 0, np.clip(np.round(scaled), 1, 255)).astype("uint8")
    np.testing.assert_array_equal(
        mod.water_vapor(torch.from_numpy(step), VARIABLES).numpy(), expected
    )


def test_satellite_angles_do_not_depend_on_time(mod, grid):
    """Why they are computed once: GOES-East is geostationary."""
    from pyorbital import orbital

    lat, lon = grid
    clat = np.asarray(lat, "float64")[::8, ::8]
    clon = np.asarray(lon, "float64")[::8, ::8]
    satz, sata = mod.satellite_angles(lat, lon)
    for when in (mod.datetime(2026, 11, 16, 3), mod.datetime(2026, 11, 18, 21, 40)):
        az, elev = orbital.get_observer_look(
            mod.GOES_SUBSAT_LON, 0.0, mod.GOES_ALT_KM, when, clon, clat, np.zeros_like(clon)
        )
        np.testing.assert_allclose(90 - elev, satz, atol=1e-6)
        np.testing.assert_allclose(az % 360, sata, atol=1e-6)


def test_geometry_cache_computes_each_valid_time_once(mod, grid):
    lat, lon = grid
    geometry = mod.TrueColorGeometry(lat, lon, torch.device("cpu"))
    start = np.datetime64("2026-11-16T18:00")
    leads = np.arange(13) * np.timedelta64(10, "m")
    geometry.prepare(start + leads)
    first = geometry.get(start + leads[3])
    np.testing.assert_array_equal(first.numpy(), mod.true_color_fields(lat, lon, start + leads[3]))

    for f in geometry.futures.values():
        f.result()
    calls = FakeRayleigh.calls
    # The next init, one slot later, shares no valid time; the one after that shares 12 of 13.
    geometry.prepare(start + np.timedelta64(10, "m") + leads)
    for f in geometry.futures.values():
        f.result()
    assert FakeRayleigh.calls - calls == 2  # one new valid time, two bands
    assert geometry.get(start + leads[3]) is first
    waited = geometry.waited
    geometry.get(start + leads[5])
    assert geometry.waited == waited  # ready: no wait

    geometry.evict_before(start + np.timedelta64(10, "m"))
    assert min(geometry.futures) == start + np.timedelta64(10, "m")


def test_geometry_cache_retries_after_a_failure(mod, grid, monkeypatch):
    lat, lon = grid
    geometry = mod.TrueColorGeometry(lat, lon, torch.device("cpu"))
    t = np.datetime64("2026-11-16T18:00")
    real = mod.true_color_fields

    def broken(*args, **kwargs):
        raise ZeroDivisionError

    broken.__wrapped__ = real
    monkeypatch.setattr(mod, "true_color_fields", broken)
    with pytest.raises(ZeroDivisionError):
        geometry.get(t)
    monkeypatch.setattr(mod, "true_color_fields", mod.true_color_fields.__wrapped__)
    assert geometry.get(t).shape == (4, H, W)


def test_geometry_runs_in_the_background(mod, grid, monkeypatch):
    """`prepare` returns at once; the work happens off the caller's thread."""
    lat, lon = grid
    geometry = mod.TrueColorGeometry(lat, lon, torch.device("cpu"))
    slow = mod.true_color_fields

    def slow_fields(*args, **kwargs):
        time.sleep(0.2)
        return slow(*args, **kwargs)

    monkeypatch.setattr(mod, "true_color_fields", slow_fields)
    t0 = time.perf_counter()
    geometry.prepare(np.datetime64("2026-11-16T18:00") + np.arange(3) * np.timedelta64(10, "m"))
    assert time.perf_counter() - t0 < 0.1
