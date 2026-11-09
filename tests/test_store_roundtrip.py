"""End-to-end store test without the model: schema -> write -> commit -> reopen -> append.

Uses a stub in place of StormScopeGOES (same grid attributes, identity crop), a local
Icechunk repo, and the stock earth2studio `IceChunkBackend`.
"""

import importlib.util
import pathlib
from collections import OrderedDict

import numpy as np
import pytest

torch = pytest.importorskip("torch")
icechunk = pytest.importorskip("icechunk")
xr = pytest.importorskip("xarray")

_spec = importlib.util.spec_from_file_location(
    "pipeline_rt",
    pathlib.Path(__file__).parents[1] / "scripts" / "stormscope_us_pipeline.py",
)
pl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pl)
pl._heavy_imports()

VARS = np.array(["abi01c", "abi02c", "abi03c", "abi07c", "abi08c", "abi09c", "abi10c", "abi13c"])
NY, NX = 6, 8


class StubModel:
    variables = VARS
    output_times = np.array([np.timedelta64(10, "m")])

    def __init__(self):
        self.y = np.arange(NY) * 3000.0 - 9000.0
        self.x = np.arange(NX) * 3000.0 + 800e3
        lat = np.linspace(40, 42, NY)[:, None].repeat(NX, 1)
        lon = np.linspace(272, 274, NX)[None, :].repeat(NY, 0)  # 0..360 like the model
        self.latitudes = torch.tensor(lat, dtype=torch.float32)
        self.longitudes = torch.tensor(lon, dtype=torch.float32)

    def crop_output(self, x, coords):
        return x, coords


def run_init(model, output_dir, init: np.datetime64, n_steps=2):
    coords = OrderedDict(
        ensemble=np.arange(1), time=np.array([init]), lead_time=np.array([np.timedelta64(0, "m")])
    )
    lead_time = np.arange(n_steps + 1) * model.output_times[0]
    backend, _ = pl.build_backend("local", str(output_dir), "unused")
    if "true_color" not in backend.root:
        pl.create_schema(backend, model, coords, lead_time, None)
    else:
        pl.extend_schema(backend, coords["time"], lead_time, pl.output_grid(model)[0])
    for step in range(n_steps + 1):
        x = torch.full((1, 1, 1, len(VARS), NY, NX), 0.4)
        x[:, :, :, -1] = 220.0  # cold cloud tops in C13
        x[..., 0, 0] = torch.nan
        step_coords = OrderedDict(
            ensemble=coords["ensemble"],
            time=coords["time"],
            lead_time=lead_time[step : step + 1],
            variable=VARS,
            y=model.y,
            x=model.x,
        )
        backend.write(*pl.step_composites(model, x, step_coords, list(VARS)))
    backend.commit(f"init {init}", rebase_with=icechunk.ConflictDetector())


def test_two_inits_roundtrip(tmp_path):
    model = StubModel()
    run_init(model, tmp_path, np.datetime64("2026-11-16T18:00"))
    run_init(model, tmp_path, np.datetime64("2026-11-16T18:10"))

    repo = icechunk.Repository.open(
        icechunk.local_filesystem_storage(str(tmp_path / "stormscope_us.icechunk"))
    )
    ds = xr.open_zarr(repo.readonly_session("main").store, consolidated=False)
    assert list(ds.time.values) == [
        np.datetime64("2026-11-16T18:00", "ns"),
        np.datetime64("2026-11-16T18:10", "ns"),
    ]
    assert ds.true_color.dims == ("ensemble", "time", "lead_time", "y", "x", "rgb")
    assert ds.true_color.dtype == np.uint8 and ds.clean_ir.dtype == np.uint8
    assert ds.true_color.attrs["grid_mapping"] == pl.GRID_MAPPING
    assert set(ds.coords) >= {"lat", "lon", "valid_time"}
    assert float(ds.lon.min()) < 0  # stored -180..180
    tc = ds.true_color.values
    assert (tc[..., 0, 0, :] == 0).all()  # NaN pixel -> fill
    assert (tc[..., 1:, 1:, :] > 0).all()  # every written step filled
    ir = ds.clean_ir.values[0, 1, 2, 3, 3]
    assert len(set(ir.tolist())) > 1  # coloured cold top
    assert ds.valid_time.values[1, 2] == np.datetime64("2026-11-16T18:30", "ns")


def test_rerun_overwrites_and_n_steps_mismatch(tmp_path):
    model = StubModel()
    run_init(model, tmp_path, np.datetime64("2026-11-16T18:00"))
    run_init(model, tmp_path, np.datetime64("2026-11-16T18:00"))  # rerun, same slice
    backend, _ = pl.build_backend("local", str(tmp_path), "unused")
    assert len(backend.root["time"][:]) == 1
    with pytest.raises(ValueError, match="n-steps"):
        pl.extend_schema(
            backend,
            np.array([np.datetime64("2026-11-16T18:10")]),
            np.arange(4) * np.timedelta64(10, "m"),
            model.y,
        )
