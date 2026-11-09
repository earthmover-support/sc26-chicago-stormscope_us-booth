"""Tests for the pipeline's pure helpers: composites, GOES slot logic, region parsing.

No GPU, model or network needed.
"""

import importlib.util
import pathlib
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

_spec = importlib.util.spec_from_file_location(
    "pipeline",
    pathlib.Path(__file__).parents[1] / "scripts" / "stormscope_us_pipeline.py",
)
pl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pl)

VARS = ["abi01c", "abi02c", "abi03c", "abi07c", "abi08c", "abi09c", "abi10c", "abi13c"]


def step(fill: dict, shape=(2, 3)) -> np.ndarray:
    """(ensemble=1, time=1, lead=1, variable, y, x) array with per-channel constants."""
    arr = np.full((1, 1, 1, len(VARS), *shape), np.nan)
    for name, value in fill.items():
        arr[..., VARS.index(name), :, :] = value
    return arr


# ---- true_color -------------------------------------------------------------


def test_true_color_shape_dtype():
    out = pl.true_color(step({"abi01c": 0.2, "abi02c": 0.3, "abi03c": 0.4}), VARS)
    assert out.shape == (1, 1, 1, 2, 3, 3)
    assert out.dtype == np.uint8


def test_true_color_synthetic_green_and_gamma():
    r, n, b = 0.3, 0.6, 0.1
    out = pl.true_color(step({"abi01c": b, "abi02c": r, "abi03c": n}), VARS)[0, 0, 0, 0, 0]
    g = 0.45 * r + 0.10 * n + 0.45 * b
    expected = np.round(np.array([r, g, b]) ** (1 / 2.2) * 255)
    np.testing.assert_array_equal(out, expected)


def test_true_color_black_is_not_missing_and_nan_is_fill():
    arr = step({"abi01c": 0.0, "abi02c": 0.0, "abi03c": 0.0})
    arr[..., VARS.index("abi02c"), 0, 0] = np.nan
    out = pl.true_color(arr, VARS)[0, 0, 0]
    assert out[0, 0, 0] == pl.RGB_FILL  # NaN red -> missing
    assert (out[1, 1] == 1).all()  # black clamps to 1, not the fill value


def test_true_color_saturates():
    out = pl.true_color(step({"abi01c": 1.5, "abi02c": 1.5, "abi03c": 1.5}), VARS)
    assert (out == 255).all()


# ---- clean_ir ---------------------------------------------------------------


@pytest.mark.parametrize(
    "bt, rgb",
    [(t, c) for t, c in pl.CLEAN_IR_TABLE],
)
def test_clean_ir_table_points(bt, rgb):
    out = pl.clean_ir(step({"abi13c": bt}), VARS)[0, 0, 0, 0, 0]
    np.testing.assert_array_equal(out, np.clip(rgb, 1, 255))


def test_clean_ir_warm_is_grey_and_darker_when_warmer():
    warm = pl.clean_ir(step({"abi13c": 300.0}), VARS)[0, 0, 0, 0, 0]
    cool = pl.clean_ir(step({"abi13c": 260.0}), VARS)[0, 0, 0, 0, 0]
    assert warm[0] == warm[1] == warm[2]
    assert cool[0] == cool[1] == cool[2]
    assert warm[0] < cool[0]


def test_clean_ir_cold_tops_are_coloured():
    out = pl.clean_ir(step({"abi13c": 213.15}), VARS)[0, 0, 0, 0, 0]
    assert len(set(out.tolist())) > 1  # not grey


def test_clean_ir_clamps_and_masks():
    arr = step({"abi13c": 150.0})
    arr[..., VARS.index("abi13c"), 0, 0] = np.nan
    arr[..., VARS.index("abi13c"), 0, 1] = 400.0
    out = pl.clean_ir(arr, VARS)[0, 0, 0]
    assert (out[0, 0] == pl.RGB_FILL).all()
    np.testing.assert_array_equal(out[0, 1], [8, 8, 8])
    np.testing.assert_array_equal(out[1, 1], [255, 255, 255])


def test_clean_ir_table_monotonic():
    temps = [t for t, _ in pl.CLEAN_IR_TABLE]
    assert temps == sorted(temps)


# ---- GOES slots -------------------------------------------------------------


def test_scan_start_parses_file_name():
    path = (
        "ABI-L2-MCMIPC/2026/320/18/"
        "OR_ABI-L2-MCMIPC-M6_G19_s20263201801172_e20263201803545_c20263201804067.nc"
    )
    assert pl.scan_start(path) == datetime(2026, 11, 16, 18, 1, 17, tzinfo=UTC)


def test_scan_slot_maps_conus_start_to_slot():
    assert pl.scan_slot(datetime(2026, 11, 16, 18, 1, 17, tzinfo=UTC)) == datetime(
        2026, 11, 16, 18, 0, tzinfo=UTC
    )
    assert pl.scan_slot(datetime(2026, 11, 16, 18, 6, 17, tzinfo=UTC)) == datetime(
        2026, 11, 16, 18, 5, tzinfo=UTC
    )


def test_floor_to_slot():
    when = datetime(2026, 11, 16, 18, 17, 59, tzinfo=UTC)
    assert pl.floor_to_slot(when) == datetime(2026, 11, 16, 18, 15, tzinfo=UTC)


def _slots(end: datetime, n: int) -> set[datetime]:
    return {end - i * timedelta(minutes=5) for i in range(n)}


def test_latest_complete_slot_picks_newest_5min_slot():
    end = datetime(2026, 11, 16, 18, 25, tzinfo=UTC)  # inits every 5 min, also on :x5
    got = pl.latest_complete_slot(_slots(end, 20), 6, timedelta(minutes=10), end)
    assert got == datetime(2026, 11, 16, 18, 25, tzinfo=UTC)


def test_latest_complete_slot_skips_gaps():
    end = datetime(2026, 11, 16, 18, 20, tzinfo=UTC)
    slots = _slots(end, 20) - {datetime(2026, 11, 16, 17, 50, tzinfo=UTC)}
    # 18:20 needs 17:50; 18:15 uses the other 5-min phase (18:15 ... 17:45), all present
    got = pl.latest_complete_slot(slots, 4, timedelta(minutes=10), end)
    assert got == datetime(2026, 11, 16, 18, 15, tzinfo=UTC)


def test_latest_complete_slot_respects_not_after():
    end = datetime(2026, 11, 16, 18, 20, tzinfo=UTC)
    got = pl.latest_complete_slot(
        _slots(end, 20), 2, timedelta(minutes=10), end - timedelta(minutes=12)
    )
    assert got == datetime(2026, 11, 16, 18, 5, tzinfo=UTC)


def test_latest_complete_slot_raises_when_none():
    with pytest.raises(FileNotFoundError):
        pl.latest_complete_slot(set(), 2, timedelta(minutes=10), datetime.now(UTC))


# ---- region / grid ----------------------------------------------------------


def test_parse_region():
    assert pl.parse_region(None) is None
    assert pl.parse_region("conus") is None
    assert pl.parse_region("36,46,-96,-82") == (36.0, 46.0, -96.0, -82.0)
    with pytest.raises(ValueError):
        pl.parse_region("46,36,-96,-82")
    with pytest.raises(ValueError):
        pl.parse_region("1,2,3")


def test_hrrr_crs_puts_origin_at_38_5n_97_5w():
    to_ll = __import__("pyproj").Transformer.from_crs(pl.HRRR_CRS, "EPSG:4326", always_xy=True)
    lon, lat = to_ll.transform(0.0, 0.0)
    assert lat == pytest.approx(38.5, abs=1e-6)
    assert lon == pytest.approx(-97.5, abs=1e-6)


def test_hrrr_crs_matches_chicago_roughly():
    # Chicago lies NE of the origin: x > 0, y > 0, within a few hundred km scale.
    from_ll = __import__("pyproj").Transformer.from_crs("EPSG:4326", pl.HRRR_CRS, always_xy=True)
    x, y = from_ll.transform(-87.63, 41.88)
    assert 700e3 < x < 950e3
    assert 300e3 < y < 550e3


def test_geozarr_attrs_transform():
    y = np.arange(4) * 3000.0 - 4500.0
    x = np.arange(5) * 3000.0
    attrs = pl.geozarr_attrs(y, x)
    assert attrs["spatial:transform"] == [3000.0, 0.0, -1500.0, 0.0, 3000.0, -6000.0]
    assert attrs["spatial:shape"] == [4, 5]
