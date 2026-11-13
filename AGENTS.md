# AGENTS.md

Goal: Low-latency StromscopeUS pipeline, running in AWS us-east-1 to sit next to the NOAA GOES-19 bucket (`noaa-goes19`, us-east-1) and the Arraylake/Icechunk storage, so there is no cross-region transfer
Template: https://github.com/earthmover-support/nvidia-gtc-berlin-2026-stormscope_eu-booth and ../nvidia-gtc-berlin-2026-stormscope_eu-booth

Arraylake repo: https://app.earthmover.io/nvidia/sc26-chicago-stormscope_us-booth

Key differences:
- spatial domain: CONUS with GOES
- https://nvidia.github.io/earth2studio/main/examples/04_nowcasting/03_stormscope_goes_example/ with '3km_10min_flash' but no MRMS radar
- output: true_color (day) and CIRA water_vapor RGB (day and night)

## Goals

Booth demo for SC26 Chicago (McCormick Place, 2026-11-15/20): run StormScope-US
(`StormScopeGOES`, `3km_10min_flash`, earth2studio 0.20.0) on GOES-19 ABI CONUS data,
stream each forecast step into Icechunk on Arraylake
(`nvidia/sc26-chicago-stormscope_us-booth`), and show the latest run on a booth screen and
a phone viewer through the Arraylake tiles service. US only; nothing of the EU setup
is kept besides its structure.

## File tree

```
.
├── scripts/        # GPU pipeline: GOES-19 fetch -> StormScope-US inference -> Icechunk/Arraylake ingest
├── presentation/   # booth screen: web app (MapLibre globe, explainer panels, live SQL), its local server, and Vercel functions for the hosted copy
├── site/           # static MapLibre globe hosted on Vercel: init/variable selector, lead-time playback
├── docs/           # end-to-end latency, stage by stage, with every improvement measured
├── pyproject.toml  # uv project; `gpu` extra adds NATTEN + earth2grid for linux+CUDA
└── README.md       # overview, viz/tiles setup, how to run the pipeline
```

## docs/

- `END2END_NEARREALTIME_PERFORMANCE.md`: latency of each stage from GOES-19 scan to the forecast playing in the browser. Baseline = the Berlin setup migrated to the US; every later change is measured on its own (before/after) and logged there.
- `GPU.md`: GPU instance options in us-east-1 and the Coiled deployment.
- `BREV.md`: the Brev launchable (setup values -> systemd service running the pipeline).

## Conventions

- `uvx pre-commit run --all-files` for ruff.
- Placeholders (`TODO-<name>`) mark infra that does not exist yet; none are left.
