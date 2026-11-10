# Open items for the user

Things only you can fix or decide. Claude keeps this list current; tick items off or
delete them when done.

## To decide

- [ ] Clean IR colour table (`CLEAN_IR_TABLE` in `scripts/stormscope_us_pipeline.py`): grey from +40 °C to −30 °C, then light blue −30 / blue −40 / green −50 / yellow −60 / red −70 / dark red −80 / white −90 °C. OK, or name a specific one, e.g. NOAA/CIMSS "Rainbow IR" or the AVN enhancement? Judge it on a real run; to discuss with colleagues.
- [ ] True colour recipe: is CIMSS natural true colour (synthetic green 0.45·C02 + 0.10·C03 + 0.45·C01, gamma 2.2) OK? Judge it on a real run; to discuss with colleagues.
- [ ] Cheaper GPU: the pipeline uses only ~11 GB of GPU memory. `g6e.4xlarge` measured: same speed as `g6e.8xlarge` at $1.98/h, now the default. Still to benchmark: `g6e.2xlarge`, `g6e.xlarge`, `g6.xlarge` (L4, $0.80/h) and `g5.xlarge` (A10G), then pick one. L4/A10G would add ~1.5–2 min latency and break the "5 minutes" slide claim. TODO rows in [docs/GPU.md, Inference timing log](docs/GPU.md#inference-timing-log).

## Done

- [x] Vercel projects and domains (created by Earthmover colleagues): hosted presentation `nvidia-sc26-chicago.earthmover.io` (project `sc26-chicago-stormscope-us-booth`), mobile viewer `nvidia-sc26-chicago-viewer.earthmover.io` (project `sc26-chicago-stormscope-us-booth-site`). `viewer_url` set in `presentation/config.json`; both Vercel proxies pinned to `iad1`, next to the us-east-1 tiles service.
- [x] Read-only Arraylake token for the hosted presentation sent to the colleagues setting up Vercel (env `ARRAYLAKE_API_TOKEN`).
- [x] GPU host: 1x NVIDIA L40S, default `g6e.4xlarge` ($1.98/h, same speed as the `g6e.8xlarge` used first), us-east-1, via Coiled cluster `stormscope-us-gpu`; see [docs/GPU.md](docs/GPU.md#default-deployment-g6e4xlarge). Deployment stopped for the GPU benchmark; restart with step 2 there.
- [x] First GPU run: 46–56 s per 12-step run (fetch ~6 s, ~4 s per step, commit ~1 s); in `run_phases_s`, panel 03 and stage 5 of `docs/END2END_NEARREALTIME_PERFORMANCE.md`.
- [x] Cadence: a new forecast every 5 min (`run_interval_min: 5`).
- [x] Booth copy on panels 03 and 05: "NVIDIA L40S GPU · ~4 s per 10-minute step", inference + ingest "<1 min".
- [x] Arraylake tiles service enabled (`tiles-dd7cd36ec0562874.compute.arraylake.app`), URLs set in `presentation/config.json`, `presentation/api/tiles.js`, `site/index.html`, `site/api/tiles.js`. Real tiles served (2026-11-09).
- [x] SQL service enabled; `sql.host` = `sql-4ae7e8fe159e81b6.compute.arraylake.app` (port 5432 reachable; first query with a token still to be tried).
- [x] GitHub repo `earthmover-support/sc26-chicago-stormscope_us-booth` exists and matches the links on the booth page and viewer.
- [x] Station marker: McCormick Place, Chicago (SC26 venue, 15–20 Nov 2026).
- [x] SQL places in date order: SC26 Chicago, GTC DC (Ronald Reagan Building), AGU26 San Francisco (Moscone), AMS 2027 Denver (Colorado Convention Center), GTC San Jose (McEnery Convention Center).
- [x] `--min-lag` default: 0. The pipeline starts a slot only after all 6 of its input files are listed in `noaa-goes19`, so it needs no fixed lag (files land about `T`+4.3 min).
- [x] earth2studio pinned to the 0.20.0 release (has `3km_10min_flash` and the IceChunkBackend fix, so the PR #51 change is in).
- [x] Design approved ("go").
