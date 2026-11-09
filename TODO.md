# Open items for the user

Things only you can fix or decide. Claude keeps this list current; tick items off or
delete them when done.

## To decide

- [ ] Clean IR colour table: is the proposed one OK (grey for warm surfaces, colour for cold cloud tops, a standard enhanced-IR look)? Or name a specific one, e.g. NOAA/CIMSS "Rainbow IR" or the AVN enhancement.
- [ ] True colour recipe: is CIMSS natural true colour (synthetic green from C01/C02/C03) OK?
- [ ] Station marker: is McCormick Place, Chicago the SC26 venue/booth location?
- [ ] SQL places: Chicago, New York, Denver, or different cities?
- [ ] `--min-lag` default for GOES-19 on AWS: start at a few minutes and tune it after measuring?
- [ ] Approve the design (playback in chat) before the build starts.

## To fix / provide

- [ ] Flux tiles service in the `nvidia` org: enable it and paste the `tile_base` URL into `presentation/config.json` and `site/`.
- [ ] SQL service host for the `nvidia` org (`sql.host` in `presentation/config.json`).
- [ ] Vercel projects and domains for the hosted presentation and the mobile viewer (replace the `viewer_url` and README links).
- [ ] Read-only Arraylake token for the hosted presentation (Vercel env).
- [ ] GPU host to run the pipeline (CUDA, NVIDIA Container Toolkit, NGC login if needed). Pick the instance type in us-east-1 (B200 = `p6-b200.48xlarge`, 8 GPUs only, ~$114/h on-demand; 1x H100 `p5.4xlarge` ~$6.88/h) and check the EC2 GPU quota / Capacity Block for the booth days.
- [ ] `ARRAYLAKE_API_TOKEN` with write access to `nvidia/sc26-chicago-stormscope_us-booth`.
- [ ] Check that the earth2studio version with `3km_10min_flash` is released or pinned to a commit.
