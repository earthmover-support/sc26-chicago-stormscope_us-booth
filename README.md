# sc26-chicago-stormscope_us-booth

[![Launch on Brev](https://brev-assets.s3.us-west-1.amazonaws.com/nv-lb-dark.svg)](https://brev.nvidia.com/launchable/deploy?launchableID=env-3M2pAl81MVfkO3sQbiqFQjKLiQ4)

The booth demo for SC26 Chicago, McCormick Place, 15 to 20 November 2026. It runs
StormScope-US nowcasts on GOES-19 ABI data over the contiguous US and streams them into
Arraylake. We stop the deployed pipeline after the event.

## Links

- Earth2Studio example: https://nvidia.github.io/earth2studio/main/examples/04_nowcasting/03_stormscope_goes_example/
- Arraylake repo: https://app.earthmover.io/nvidia/sc26-chicago-stormscope_us-booth
- Hosted presentation: https://nvidia-sc26-chicago.earthmover.io/. To centre it on another
  venue, add `?location=` with a name from `sql.places` in
  [`presentation/config.json`](presentation/config.json). A browser that already allows
  location access uses its own position instead. See
  ["Here"](presentation/README.md#here) for the rules.
  - SC26 Chicago (default): https://nvidia-sc26-chicago.earthmover.io/?location=SC26%20Chicago
  - GTC DC: https://nvidia-sc26-chicago.earthmover.io/?location=GTC%20DC
  - AGU26 SF: https://nvidia-sc26-chicago.earthmover.io/?location=AGU26%20SF
  - AMS 2027 Denver: https://nvidia-sc26-chicago.earthmover.io/?location=AMS%202027%20Denver
  - GTC San Jose: https://nvidia-sc26-chicago.earthmover.io/?location=GTC%20San%20Jose
- Mobile viewer: https://nvidia-sc26-chicago-viewer.earthmover.io/

[`scripts/stormscope_us_pipeline.py`](scripts/stormscope_us_pipeline.py) runs
`StormScopeGOES` (`3km_10min_flash`, earth2studio 0.20.0) end to end:

1. Find the newest 10-minute slot `T` whose six input frames, `T`-50 to `T`, are on NOAA's
   public `noaa-goes19` bucket.
2. Roll the model forward in 10-minute steps on the 3 km HRRR grid.
3. Write each step to Icechunk on Arraylake as soon as the model produces it.

GOES-19 files reach S3 about 4.3 min after their slot time and need no credentials. The
pipeline therefore runs a few minutes behind real time. It uses no MRMS radar. See
[Pipeline script](#pipeline-script) and
[docs/END2END_NEARREALTIME_PERFORMANCE.md](docs/END2END_NEARREALTIME_PERFORMANCE.md).
To run it on a GPU VM, use Coiled ([docs/GPU.md](docs/GPU.md)) or a Brev launchable
([docs/BREV.md](docs/BREV.md)).

## Get real-time forecasts in your Arraylake bucket deploying on Brev in under 30 min

1. Get the Earthmover **Community** tier: https://docs.earthmover.io/pricing
2. Create an Arraylake org and an empty repo, either in
   [your own bucket](https://docs.earthmover.io/setup/manage-storage#bring-your-own-bucket)
   or in
   [Earthmover-managed storage](https://docs.earthmover.io/setup/manage-storage#earthmover-managed-storage).
   The pipeline writes the schema on its first run.
3. Create an `ARRAYLAKE_API_TOKEN` with write access to that repo:
   https://docs.earthmover.io/setup/org-access#creating-and-managing-api-keys
4. Get a [Brev](https://brev.nvidia.com) account. Launching an instance requires credit
   card details.
5. Start the launchable:

   [![Launch on Brev](https://brev-assets.s3.us-west-1.amazonaws.com/nv-lb-dark.svg)](https://brev.nvidia.com/launchable/deploy?launchableID=env-3M2pAl81MVfkO3sQbiqFQjKLiQ4)

   Set `ARRAYLAKE_API_TOKEN` and `ARRAYLAKE_REPO` (`<org>/<repo>`); the other setup
   values can keep their defaults.
6. Less than 30 min later, fresh forecasts arrive in your repo. The first start pulls the
   container, installs the dependencies and compiles the model; after that, a new
   forecast follows each new GOES-19 scan. Inspect the data in the Arraylake web app
   (`https://app.earthmover.io/<org>/<repo>`). To follow progress on the VM, use the
   [Brev CLI](https://docs.nvidia.com/brev/latest/cli/getting-started)
   (`brev login`, then `brev ls` for the instance name):

   ```bash
   brev exec <instance> 'sudo journalctl -u stormscope-us -n 50 --no-pager'  # one look
   brev shell <instance>                                                     # then: sudo journalctl -u stormscope-us -f
   ```

   See [docs/BREV.md](docs/BREV.md) for more commands.

## Frontend Deployments

| | Runs as | Live SQL | Audience | URL |
|---|---|---|---|---|
| Booth presentation ([`presentation/`](presentation/README.md)) | `uv run presentation/server.py` on the booth machine, full screen on the TV | editable | SC26 visitors | `http://localhost:8000` on the booth machine |
| Hosted presentation ([`presentation/`](presentation/README.md#hosted-on-vercel)) | Vercel project `sc26-chicago-stormscope-us-booth`, root directory `presentation` | fixed: the venue queries only, cached per init | internal sharing, unlisted URL | `nvidia-sc26-chicago.earthmover.io` |
| Mobile site ([`site/`](site/README.md)) | Vercel project `sc26-chicago-stormscope-us-booth-site`, root directory `site`, static | none | phones, through the booth QR code | `nvidia-sc26-chicago-viewer.earthmover.io` |

The domains follow the GTC Berlin pattern. The Vercel project names use only hyphens, so
Vercel does not truncate the `*.vercel.app` fallback domains.

Both presentation deployments serve the same `presentation/web/` page and use the same
logic in `presentation/booth.py`. Only the `sql_editable` flag in `/api/config` differs.
`server.py` answers `true`. The Vercel functions in `presentation/api/` answer `false`.

## Viz

### Tiles service

The tiles come from a public Arraylake tiles service in the `nvidia` org,
`tiles-dd7cd36ec0562874.compute.arraylake.app`. Its URL is `tile_base` in
`presentation/config.json` and `TILES` in `site/index.html` and in both `api/tiles.js`
files. Change all four together.

The service must be public because the booth screen and the phones fetch tiles directly
from the browser, and a browser cannot attach an `Authorization` header. Anyone with a tile
URL can fetch the rendered tile. The underlying chunks stay private. Run the service in
us-east-1 next to the data, and pin the replicas during booth hours:

```
al compute enable nvidia tiles --sku-code s --is-public
al compute update nvidia <tiles-id> --min-replicas 8 --max-replicas 8
```

After booth hours, set `--min-replicas 0`. After the event, run `al compute disable`.

The service keeps no cache of rendered tiles. Each pod caches on its own and starts empty.

### Render parameters

These parameters apply to `true_color` and `water_vapor`:

| Parameter | Value | Why |
| --- | --- | --- |
| `style` | `raster/rgb` | Real 3-band composite. Pass `variables=true_color` with no `rgb` selector. |
| `colorscalerange` | `0,255` | The pipeline stores both composites as uint8 0–255 (see [Pipeline script](#pipeline-script)). |
| `lead_time` | `PT10M` | 13 frames: 0, 10, …, 120 minutes. Lead 0 is the observed satellite frame. The other 12 are forecast. |
| `ensemble` | `1` | Single member, int8, numbered from 1. Every variable is 5-D, so this parameter is required. |

`true_color` is black on the night side. `water_vapor` works day and night and shows cloud
height and moist and dry air. The booth page and the mobile viewer therefore start on
`water_vapor` while it is dark at the venue.

### Tile proxy

The Vercel deployments do not send the browser to the tiles service directly. The site
requests `/tiles/...` on any `https:` origin. The hosted presentation gets
`tile_base: /tiles/<repo>` from `/api/config`. `vercel.json` rewrites `/tiles/*` to
`api/tiles.js`. This function is the same in [`site/api/`](site/api/tiles.js) and
[`presentation/api/`](presentation/api/tiles.js). It is a Node.js function pinned to
`iad1`. Move it next to the tiles service's region once that region is known.

The function does these things:

- It forwards only the requests that its page makes. Any other path returns `404`.
- It keeps successful responses in two caches. The first is Vercel's CDN, one cache per edge
  region and hostname. The second is the Runtime Cache, which all regions and hostnames
  share because the function always runs in one region. Tiles stay for a day. Errors such
  as a `504` are not cached.
- It merges concurrent misses that land on the same function instance into one request to
  the tiles service.
- It tags each tile `tiles` and `init-<YYYYMMDDHHMM>`. To clear a rerun init, run
  `vercel cache invalidate --tag init-202611161800`. A redeploy also empties the CDN cache.

The two copies differ in the paths they forward:

| Copy | Forwards |
| --- | --- |
| `site/api/tiles.js` | tiles on branch `main`, and the `_meta` init list of this repo. It keeps the init list for 30 s. |
| `presentation/api/tiles.js` | tiles on branch `main` or on a snapshot id. The booth page pins each run to its snapshot. |

On a local `http:` origin, both pages fetch tiles from the tiles service directly. So does
the booth's `server.py`.

## Running it

The model needs a CUDA GPU. On the GPU host, install the GPU extra with
`uv sync --extra gpu`. It takes NATTEN's prebuilt wheels from <https://whl.natten.org/>
and also builds `earth2grid`. Then run the [pipeline script](#pipeline-script).

The pipeline reads its credentials from a local `.env` (see [`.env.example`](.env.example)):

- `ARRAYLAKE_API_TOKEN`: the ingest target. GOES-19 data is public.

The pipeline makes one commit per init, after the last step. A run that stops partway
therefore publishes nothing. A rerun of the same init overwrites its slice.

## Pipeline script

```
GOES-19 ABI CONUS (noaa-goes19) → Earth2Studio StormScopeGOES Flash → Icechunk/Arraylake publish → tile dashboard
```

The script lists the bucket to find the freshest complete input window. `GOES.available`
is not enough for this. It reports any hour that has a file in it, and `fetch_data` then
serves the closest older scan without a warning.

The script uploads each step in the background while it computes the next one. It
publishes through plain `earth2studio.io.IceChunkBackend`, with
`arraylake.Client.get_icechunk_storage`, to the root group of
`nvidia/sc26-chicago-stormscope_us-booth`.

Each run makes one commit with the message `stormscope-us <init> lead 0-120 min`. The booth
server finds each run's snapshot from this message, so keep the format. In that commit,
the run extends the schema by its init time and appends along `time`. All runs must
therefore use the same `--n-steps` and `--region`.

```bash
uv run python scripts/stormscope_us_pipeline.py --n-steps 3                    # local Icechunk in outputs/
uv run python scripts/stormscope_us_pipeline.py --start-time 2026-11-16T18:00 --n-steps 12
uv run python scripts/stormscope_us_pipeline.py --region 36,46,-96,-82          # Midwest box only
uv run python scripts/stormscope_us_pipeline.py --publish-target arraylake
```

| Flag | Default | Notes |
|---|---|---|
| `--start-time` | freshest slot with all 6 input frames listed | ISO 8601 UTC on a 10-min boundary. If the script cannot list the bucket, it uses 30 min before now. |
| `--min-lag` | `0` | minutes that must pass after a slot time before the script considers that slot |
| `--wait-seconds` | `5` | sleep before the next look when there is no new init or a pass failed |
| `--n-steps` | `12` | 10-min steps |
| `--region` | `$STORMSCOPE_REGION` or full CONUS | `lat_min,lat_max,lon_min,lon_max`, west negative. Flash `set_domain` with 25 px context. The script stores the region cropped. |
| `--output-dir` | `outputs` | local Icechunk store |
| `--publish-target` | `$STORMSCOPE_PUBLISH_TARGET` or `local` | `local` or `arraylake` |
| `--arraylake-repo` | `$ARRAYLAKE_REPO` or `nvidia/sc26-chicago-stormscope_us-booth` | required with `arraylake`, which also needs `ARRAYLAKE_API_TOKEN` |
| `--device` | `auto` | `auto`, `cuda` or `cpu` |

The script stores two RGB composites, not the 8 raw channels. Both have the shape
`(ensemble, time, lead_time, y, x, rgb)` and are uint8 in 0–255 on the HRRR Lambert
conformal grid:

- 1024 × 1792 at 3 km for CONUS.
- `x` and `y` in meters, with the CF grid mapping `hrrr_lambert_conformal`.
- 2-D `lat` and `lon`, each one chunk.
- `ensemble` is int8, numbered from 1.

The script computes each composite in 0–1 and stores it as `round(x * 255)`, clipped to
1–255. A missing pixel is 0, the Zarr `fill_value`. A pixel is missing when it is outside
the GOES view or the region, or when its step is not written yet. There is no CF
`_FillValue`.

- `true_color`: CIMSS natural true color from ABI reflectances. ABI has no green band, so
  the script synthesizes green:
  ```
  R = C02 (0.64 µm)    G = 0.45·C02 + 0.10·C03 (0.86 µm) + 0.45·C01    B = C01 (0.47 µm)
  ```
  The script first corrects the reflectances, as satpy's ABI `true_color` does, then
  stretches them. Correct first: a stretch alone brightens the bluish Rayleigh haze with the
  surface.
  1. Sun angle: divide each band by cos(sun zenith), fading out from 88° to 95°.
  2. Rayleigh: subtract the scattered-light reflectance from C01 and C02 (pyspectral,
     `us-standard`, `rayleigh_only`, GOES-East geometry). Over bright cloud (C02 above 20 %)
     the correction is relaxed, as pyspectral does.
  3. Terminator: fade to black between sun zenith 55° and 90° (satpy `sunz_reduced`, from
     the FCI recipe), so the image dims into night.
  4. Stretch: EUMETSAT's true-color contrast curve, as in the Berlin demo. It maps
     reflectance (0–100 % as 0–255) `[0, 30, 60, 120, 190, 255]` to
     `[0, 110, 160, 210, 240, 255]`, linear in between.

  The angles and the Rayleigh lookup run on every 8th pixel and are interpolated back.
  They depend only on the grid and the valid time, so they are computed in a background
  thread before they are needed (`TrueColorGeometry`): after each commit, the pipeline
  queues the valid times of the next init while it waits for the next GOES file. Steps 1
  to 4 then run on the GPU in torch, next to the rollout, and only the bytes are copied
  back. `water_vapor` runs on the GPU as well.
- `water_vapor`: CIRA Simple Water Vapor RGB, day and night. It uses inverted brightness
  temperatures, linear, gamma 1:
  - R = C13, 278.96 → 202.29 K: cloud height.
  - G = C08 (6.19 µm), 242.67 → 214.66 K: upper-level moisture.
  - B = C10 (7.34 µm), 261.03 → 245.12 K: low-to-mid moisture.

  NOAA's Air Mass RGB needs C12 (9.6 µm), which StormScope-US does not predict.
