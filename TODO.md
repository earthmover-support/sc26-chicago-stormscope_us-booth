# Open items for the user

Things only you can fix or decide. Claude keeps this list current; tick items off or
delete them when done.

## To decide

- [ ] Clean IR colour table (`CLEAN_IR_TABLE` in `scripts/stormscope_us_pipeline.py`): grey from +40 °C to −30 °C, then light blue −30 / blue −40 / green −50 / yellow −60 / red −70 / dark red −80 / white −90 °C. OK, or name a specific one, e.g. NOAA/CIMSS "Rainbow IR" or the AVN enhancement? Judge it on a real run.
- [ ] True colour recipe: is CIMSS natural true colour (synthetic green 0.45·C02 + 0.10·C03 + 0.45·C01, gamma 2.2) OK? Judge it on a real run.
- [ ] Booth copy on panels 03 and 05 (`presentation/web/index.html`): the GPU model ("NVIDIA GPU", was "H200") and the data-flow stage latencies (TBD until measured).
- [ ] Run every 5 min instead of 10? GOES-19 scans CONUS every 5 min (see Candidates in `docs/END2END_NEARREALTIME_PERFORMANCE.md`).

## To fix / provide

- [ ] Flux tiles service in the `nvidia` org (us-east-1): enable it and replace the `TODO-tiles-host` URLs in `presentation/config.json` (`tile_base`), `presentation/api/flux.js`, `site/index.html` and `site/api/flux.js`.
- [ ] SQL service host for the `nvidia` org (`sql.host` in `presentation/config.json`, empty until then, which shows SQL as disabled).
- [ ] Vercel projects and domains for the hosted presentation and the mobile viewer: replace `viewer_url` (`TODO-viewer-url`) in `presentation/config.json` and the links in `README.md`. Both Vercel proxies are pinned to `iad1`; move them if the tiles service is not in us-east-1.
- [ ] GitHub repo: the booth page and viewer link to `github.com/earthmover-support/sc26-chicago-stormscope_us-booth` (assumed name; this repo has no remote yet).
- [ ] Read-only Arraylake token for the hosted presentation (Vercel env).
- [ ] GPU host to run the pipeline (CUDA, NVIDIA Container Toolkit, NGC login if needed). Pick the instance type in us-east-1 (B200 = `p6-b200.48xlarge`, 8 GPUs only, ~$114/h on-demand; 1x H100 `p5.4xlarge` ~$6.88/h) and check the EC2 GPU quota / Capacity Block for the booth days.
- [ ] `ARRAYLAKE_API_TOKEN` with write access to `nvidia/sc26-chicago-stormscope_us-booth`.
- [ ] First GPU run: `docker compose up --build` has not been built or run yet (the Mac cannot build the CUDA image). Check the image build, the first model load, and `--region`. Then copy the printed `timing:` line into the baseline of `docs/END2END_NEARREALTIME_PERFORMANCE.md` and `run_phases_s` in `presentation/config.json` (currently estimates: ic 60 s, step 5 s, commit 6 s).

## Done

- [x] Station marker: McCormick Place, Chicago (SC26 venue, 15–20 Nov 2026).
- [x] SQL places in date order: SC26 Chicago, GTC DC (Ronald Reagan Building), AGU26 San Francisco (Moscone), AMS 2027 Denver (Colorado Convention Center), GTC San Jose (McEnery Convention Center).
- [x] `--min-lag` default: 0. The pipeline starts a slot only after all 6 of its input files are listed in `noaa-goes19`, so it needs no fixed lag (files land about `T`+4.3 min).
- [x] earth2studio pinned to the 0.20.0 release (has `3km_10min_flash` and the IceChunkBackend fix, so the PR #51 change is in).
- [x] Design approved ("go").
