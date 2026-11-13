# Booth screen

The web app for the SC26 Chicago booth. It shows these parts:

- A MapLibre globe fixed on the contiguous US, with the latest StormScope-US run from
  Arraylake.
- Rotating explainer panels.
- A live ingest strip.
- QR codes.
- A live Zax-SQL query.

It runs locally on the booth machine. A copy is also
[hosted on Vercel](#hosted-on-vercel) for internal sharing, with the SQL editor locked. The
[Deployments](../README.md#deployments) table compares the two.

```
presentation/
  server.py        booth: stdlib HTTP server + Arraylake/SQL pollers (uv inline deps)
  booth.py         logic shared by server.py and api/: runs, commits, SQL, public config
  api/             hosted: Vercel Python functions for /api/config, /api/state, /api/sql,
                   and tiles.js, the tile proxy
  requirements.txt hosted: the functions' dependencies
  vercel.json      hosted: build, output directory, function timeout
  config.json      everything tunable: tile service, variables, timings, location, SQL
  package.json     MapLibre GL + qrcode-generator, vendored so the booth runs without CDNs
                   (the dark CARTO basemap and the tiles service still need the network)
  record_video.sh  records the live page to an MP4, the fallback for a booth without internet
  web/             index.html, app.css, app.js
```

## Run

```bash
cd presentation && npm install && cd ..        # once: vendors MapLibre into node_modules
uv run presentation/server.py                  # live → http://127.0.0.1:8000
uv run presentation/server.py --demo           # rehearsal: fake commits + SQL, no Arraylake
```

`server.py` reads `ARRAYLAKE_API_TOKEN` from the repo's `.env`, and optionally
`ARRAYLAKE_SQL_HOST`. The token stays on the server. The browser receives only `/api/*` JSON
and public tile URLs.

`server.py` reads `config.json` when it starts. Restart it after you edit the file.

Booth window, full screen:

```bash
chromium --app=http://127.0.0.1:8000 --window-position=0,0 --window-size=1920,1080 \
         --noerrdialogs --disable-session-crashed-bubble
```

## Keys

| Key | Action |
| --- | --- |
| ← / → | previous / next panel (auto-rotation starts again after 60 s) |
| Space | pause / resume panel rotation |
| P | pause / resume the forecast loop |
| O | loop / play once (stops on +120) |
| S | cycle playback speed (slow 1 s / medium 0.5 s / fast 0.25 s per frame) |
| T / W | `true_color` / `water_vapor` |
| 1–9, L | pick an initialization (1 = L = latest) |
| C | collapse / expand the ingest strip |

Every toggle (loop, pause, speed, variable, init, rotation, strip) goes back to its default
after `attract_reset_s` seconds without input. `attract_reset_s` is in `config.json` and is
180 s. A visitor's click therefore does not stay for the day.

## Here

"Here" sets three things: the "you are here" marker, the day/night default variable and
the default place of the live SQL query. The page starts and resets on `true_color` while
the sun is up here, and on `water_vapor` while it is dark.

The page takes "here" from the first of these that applies:

1. The browser's location, if the browser already has location permission and the location
   is inside `data_bounds`. The page never asks for permission. The marker then reads only
   "you are here". On the hosted page the SQL default stays on the venue: its server
   runs only the venue queries, never a query for a coordinate.
2. `?location=<name>` in the page URL, for example `?location=Denver`. Use it to run one
   screen at another venue without a config edit. The camera shifts so that the venue
   stays on screen. The root README [lists the link for each venue](../README.md#links).
3. `location` in `config.json`, which is `"Chicago"`.

Options 2 and 3 name an entry in `sql.places`, the venue chips on slide 8. Add a new venue
there first.

## Before the event

1. **Tiles.** The page uses the [Arraylake tiles service](../README.md#tiles-service),
   set as `tile_base` in `config.json`. Each pod of the service starts with an empty
   cache. Before the doors open, load the booth page once and let one run play. To check
   that the service is up:
   ```bash
   B=<tile_base from config.json>
   curl -o t.png -w '%{http_code}\n' "$B/main/tiles/WebMercatorQuad/3/2/3?variables=true_color&style=raster/rgb&colorscalerange=0,255&time=<INIT>&lead_time=10%20minutes&ensemble=1&f=png"
   ```
2. **Inits.** The page reads the root group of `nvidia/sc26-chicago-stormscope_us-booth`.
   The pipeline appends the init of every run to `time` and never drops one. The page
   offers the newest 288 inits (`max_runs`): the past 24 h at one run per 5 min.

   The server reads the `time` coordinate again each time `main` moves. Each tile picks its
   frame with `time=` and `lead_time=` on the newest snapshot that holds its run, so the
   browser can cache it. The server finds the snapshot of each run from its
   [commit message](../README.md#pipeline-script).
3. **SQL.** Enable the service with `al compute enable nvidia sql --sku-code xs`. Its
   hostname, `sql-***.compute.arraylake.app`, is `sql.host` in
   `config.json`. `ARRAYLAKE_SQL_HOST=...` in `.env` overrides it. An empty host shows SQL
   as disabled. The service scales to zero, so run one query before visitors arrive.

   Panel 08 is a live editor. Click a venue chip (`sql.places`), or type any single
   `SELECT` or `WITH` statement and press ⌘/Ctrl+Enter. Esc leaves the box. The
   chips are cities: Chicago, Denver, New York, Dallas, Los Angeles. A chip fills the
   editor and runs the query at once.
   Reset only fills the editor.

   The server runs the query with the token. The browser never sees the token. For each
   new init, the server also runs the query once by itself. It resets the editor to the
   first venue and keeps that result until the next init.

   The server replaces `{init}` with the newest complete init, and fills `{lat}`, `{lon}`
   and `{box}` in `sql.query` per venue. `lat` and `lon` are 2-D pixel coordinates, so
   filter on a `BETWEEN` box, never on equality.
4. **Variables.** `true_color` and `water_vapor` use the
   [render parameters](../README.md#render-parameters) in the root README. To add more,
   add them under `variables` in `config.json`.
5. **Run length.** The strip and scrubber show the observed +0 frame plus 12 steps, +10 to
   +120 min (`lead_steps`, `lead_step_min`). `run_phases_s` are the strip's per-phase
   lengths, measured on an L40S: fetch 1.3 s with the frame cache (only the newest
   MCMIPC file is new per cycle, see
   [END2END_NEARREALTIME_PERFORMANCE.md](../docs/END2END_NEARREALTIME_PERFORMANCE.md)),
   3.3–4.1 s per step, commit 0.5–0.7 s
   ([GPU.md](../docs/GPU.md#inference-timing-log)). `run_interval_min`
   is the init cadence, one per 5-min CONUS scan.
6. **QR code.** `viewer_url` in `config.json` sets the first QR code on the last panel,
   slide 8.
7. **Time zone.** The page shows every time in `timezone` from `config.json`,
   `America/Chicago`. The booth machine's and the hosted viewer's time zone settings have
   no effect. Only the SQL `WHERE time = TIMESTAMP '{init}'` stays in UTC.
8. **Offline backup.** With tiles and SQL up, save a fallback in case the venue has no
   internet:
   ```bash
   uv run presentation/server.py --fetch-offline   # a rerun continues where it stopped
   uv run presentation/server.py --offline         # no network needed
   ```
   The fetch saves these into `presentation/offline/`, which git ignores:
   - the 3 newest runs, both variables, tiles up to z5.
   - the Carto basemap for the same zooms.
   - the fonts.
   - the venue SQL results of each run.

   `--offline` replays the saved runs on the demo cadence, one new run every 10 min. The
   header reads REPLAY. The QR codes still point online, so phones use mobile data. As a
   last resort, `record_video.sh` records the live page to an MP4.

## Hosted on Vercel

The same page, for internal sharing at an unlisted URL. It differs from the booth in these
ways:

- **SQL is locked.** `/api/config` answers `sql_editable: false`. The editor is
  read-only, Reset is hidden, and the venue chips pick the query. Run sends
  `GET /api/sql?place=<venue>&init=<newest init>`. The function runs only the
  `config.json` query for a `sql.places` entry, and only for an init on the 10-minute grid
  from the last 7 days. It rejects all other requests, including query text and POSTs. The
  CDN keeps each answer for a day.
- **No pollers.** `/api/state` reads the commits and the `time` coordinate on each
  request. The CDN caches the answer for 5 s with stale-while-revalidate.
- **Tiles go through the [tile proxy](../README.md#tile-proxy).** `/api/config` answers
  `tile_base: /tiles/<repo>`.
- **Small windows.** A window smaller than 1920 × 1080 shows the booth layout zoomed down to
  fit.
- **Vendored libraries.** The build copies them into `web/vendor/` (`npm run vendor`); the phone site in `site/` does the same.

Vercel project settings: root directory `presentation`, framework preset "Other". The
install command, build command and output directory come from `vercel.json`. Environment
variables:

| Variable | Value |
| --- | --- |
| `ARRAYLAKE_API_TOKEN` | read-only token with access to `nvidia/sc26-chicago-stormscope_us-booth`. It is also the SQL password. |
| `ARRAYLAKE_SQL_HOST` | optional, overrides `sql.host` in `config.json` |

Functions can run for 60 s (`maxDuration`), which is enough for a cold SQL service.
`vercel.json` skips deploys of commits that change nothing under `presentation/`.

To check a build locally without a deploy, use a throwaway copy. `vercel build` writes a
`pyproject.toml` and a `uv.lock` next to `requirements.txt`.

```bash
B=$(mktemp -d) && git -C presentation ls-files -co --exclude-standard | grep -v '^node_modules' \
  | tar -C presentation -cf - -T - | tar -C "$B" -xf -
mkdir "$B/.vercel" && echo '{"projectId":"local","orgId":"local","settings":{"framework":null}}' > "$B/.vercel/project.json"
(cd "$B" && vercel build --yes)
```

## Panels

1. AI weather nowcasting: six observed GOES-19 frames, then twelve AI frames, to +120 min.
2. Earth observations: GOES-19 ABI, the two composites with live +0 previews. Click a
   preview to switch the globe layer.
3. The AI model: StormScope-US Flash, a distilled diffusion model on the 3 km HRRR grid.
4. The pipeline: Earth2Studio fetch, predict, write, serve.
5. Data flow: stage latencies, from the
   [end-to-end performance doc](../docs/END2END_NEARREALTIME_PERFORMANCE.md).
6. Arraylake + Icechunk: overlapped uploads, one atomic commit per run.
7. The data lake: recent commits, time travel.
8. Your turn: viewer and raw-tile QR codes, live SQL over the event venues.

The strip's countdown and phase activity are labelled estimates. The API reports
publications, not GPU progress. The diagrams are schematics, not live measurements. The
SQL query reports the mean `true_color` brightness: high means cloudy, low means clear or
dark.
