# AGENTS.md

Goal: Low-latency StromscopeUS pipeline, running in AWS us-east-1 to sit next to the NOAA GOES-19 bucket (`noaa-goes19`, us-east-1) and the Arraylake/Icechunk storage, so there is no cross-region transfer
Template: https://github.com/earthmover-support/nvidia-gtc-berlin-2026-stormscope_eu-booth and ../nvidia-gtc-berlin-2026-stormscope_eu-booth

Arraylake repo: https://app.earthmover.io/nvidia/sc26-chicago-stormscope_us-booth

Key differences:
- spatial domain: CONUS with GOES
- https://nvidia.github.io/earth2studio/main/examples/04_nowcasting/03_stormscope_goes_example/ with '3km_10min_flash' but no MRMS radar
- output: true_color and color-enhanced Clean IR for nights

## Goals

Booth demo for SC26 Chicago (McCormick Place, 2026-11-15/20): run StormScope-US
(`StormScopeGOES`, `3km_10min_flash`, earth2studio 0.20.0) on GOES-19 ABI CONUS data,
stream each forecast step into Icechunk on Arraylake
(`nvidia/sc26-chicago-stormscope_us-booth`), and show the latest run on a booth screen and
a phone viewer through the Earthmover Flux tiles service. US only; nothing of the EU setup
is kept besides its structure.

## File tree

```
.
├── scripts/        # GPU pipeline: GOES-19 fetch -> StormScope-US inference -> Icechunk/Arraylake ingest
├── tests/          # pytest: composites, GOES slot logic, local store roundtrip (no GPU)
├── presentation/   # booth screen: web app (MapLibre globe, explainer panels, live SQL), its local server, and Vercel functions for the hosted copy
├── site/           # static MapLibre globe hosted on Vercel: init/variable selector, lead-time playback
├── docs/           # end-to-end latency, stage by stage, with every improvement measured
├── docker/, Dockerfile, compose.yaml  # the pipeline as a container on a CUDA host
├── pyproject.toml  # uv project; `gpu` extra adds NATTEN + earth2grid for linux+CUDA
├── TODO.md         # what the user still has to fix or decide
└── README.md       # overview, viz/tiles setup, how to run the pipeline
```

## docs/

- `END2END_NEARREALTIME_PERFORMANCE.md`: latency of each stage from GOES-19 scan to the forecast playing in the browser. Baseline = the Berlin setup migrated to the US; every later change is measured on its own (before/after) and logged there.

## Conventions

- `uv run pytest` must pass (no GPU needed); `uvx pre-commit run --all-files` for ruff.
- Keep `TODO.md` current whenever a placeholder, assumption or blocker needs the user.
- Placeholders (`TODO-tiles-host`, empty `sql.host`, `TODO-viewer-url`) mark infra that does not exist yet.
