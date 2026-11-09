# Booth screen

Web app for the SC26 Chicago booth: a MapLibre globe fixed on the contiguous US showing the
latest StormScope-US run from Arraylake, rotating explainer panels, a live ingest strip,
QR codes and a live Zax-SQL query. It runs locally on the booth machine and is also
[hosted on Vercel](#hosted-on-vercel) for internal sharing, with the SQL editor locked.

```
presentation/
  server.py        booth: stdlib HTTP server + Arraylake/SQL pollers (uv inline deps)
  booth.py         logic shared by server.py and api/: runs, commits, SQL, public config
  api/             hosted: Vercel Python functions for /api/config, /api/state, /api/sql;
                   tiles.js, the tile proxy
  requirements.txt hosted: the functions' dependencies
  vercel.json      hosted: build, output directory, function timeout
  config.json      everything tunable: tile service, variables, timings, station, SQL
  package.json     MapLibre GL + qrcode-generator, vendored so the booth runs without CDNs
                   (the dark CARTO basemap and the Earthmover Compute tiles still need the network)
  record_video.sh  records the live page to an MP4, the fallback for a booth without internet
  web/             index.html, app.css, app.js
```

## Run

```bash
cd presentation && npm install && cd ..        # once: vendors MapLibre into node_modules
uv run presentation/server.py                  # live → http://127.0.0.1:8000
uv run presentation/server.py --demo           # rehearsal: fake commits + SQL, no Arraylake
```

`server.py` reads `ARRAYLAKE_API_TOKEN` (and optionally `ARRAYLAKE_SQL_HOST`) from the repo's
`.env`. The token stays on the server; the browser only gets `/api/*` JSON and public tile URLs.

Booth window (full screen):

```bash
chromium --app=http://127.0.0.1:8000 --window-position=0,0 --window-size=1920,1080 \
         --noerrdialogs --disable-session-crashed-bubble
```

## Keys

| Key | Action |
| --- | --- |
| ← / → | previous / next panel (auto-rotation resumes after 60 s) |
| Space | pause / resume panel rotation |
| P | pause / resume the forecast loop |
| O | loop / play once (stops on +120) |
| S | cycle playback speed (slow 1 s / medium 0.5 s / fast 0.25 s per frame) |
| T / I | `true_color` / `clean_ir` |
| 1–9, L | pick an initialisation (1 = L = latest) |
| C | collapse / expand the ingest strip |

Every toggle (loop, pause, speed, variable, init, rotation, strip) reverts to the defaults
after `attract_reset_s` (config.json, 180 s) without any input, so a visitor's click never
sticks for the day. The page starts (and resets) on `true_color` while the sun is up at
`station` (McCormick Place) and on `clean_ir` while it is dark. `config.json` is read when
`server.py` starts: restart it after editing.

## Before the event

1. **Tiles**: the `nvidia` org's Arraylake tiles service (public, so browsers and phones
   fetch tiles without a token) is `tiles-dd7cd36ec0562874.compute.arraylake.app`; its URL is
   in `tile_base` (`config.json`), `api/tiles.js` and `../site/` (see
   [Viz](../README.md#viz)). Each pod caches on its own and
   starts empty, so load the booth page once and let one run play before doors open.
2. **Inits**: the page reads `nvidia/sc26-chicago-stormscope_us-booth` (root group). The
   pipeline appends every run's init to `time` and never drops one; the page offers the
   newest 144, the past 24 h (`max_runs`). The server re-reads the `time` coordinate
   whenever `main` moves, and each tile picks its frame with `time=` + `lead_time=` on the
   newest snapshot holding that run, so the browser can cache it. The server finds each
   run's snapshot from commit messages like `stormscope-us 2026-11-16T18:00 lead 0-120 min`.
   Quick check that the tile server is up:
   ```bash
   B=<tile_base from config.json>
   curl -o t.png -w '%{http_code}\n' "$B/main/tiles/WebMercatorQuad/3/2/3?variables=true_color&style=raster/rgb&colorscalerange=0,255&time=<INIT>&lead_time=10%20minutes&ensemble=0&f=png"
   ```
3. **SQL**: `al compute enable nvidia sql --sku-code xs`; its hostname
   (`sql-4ae7e8fe159e81b6.compute.arraylake.app`) is in `config.json` (`sql.host`; empty
   shows SQL as disabled) or `.env`
   (`ARRAYLAKE_SQL_HOST=...`, wins). The service scales to zero, so fire one query before
   visitors arrive. Panel 08 is a live editor: click a venue chip (`sql.places`) or type
   any single `SELECT`/`WITH` statement and press ⌘/Ctrl+Enter; Esc leaves the box. The
   venue chips are the events in date order: SC26 Chicago, GTC DC, AGU26 San Francisco,
   AMS 2027 Denver, GTC San Jose. A chip fills the editor and runs at once; Reset only
   fills it. The server runs the query (with the token; the browser never sees it), and
   once by itself for each new init: it resets the editor to the first venue and keeps that
   result until the next init. `{init}` is replaced by the newest complete init;
   `{lat}`/`{lon}`/`{box}` in `sql.query` are filled per venue. `lat`/`lon` are 2-D pixel
   coordinates, so filter on a `BETWEEN` box, never on equality.
4. **Variables**: `true_color` and `clean_ir` are both uint8 0-255 RGB composites
   (`raster/rgb`, `colorscalerange` `0,255`). Add more under `variables` in `config.json`.
5. **Run length**: the strip and scrubber show the observed +0 frame plus 12 steps,
   +10 to +120 min (`lead_steps`, `lead_step_min`). Keep the commit-message format in the
   pipeline: `stormscope-us <init> ...`, one commit per init. `run_phases_s` are estimates
   for the strip's countdown; replace them with measured values
   ([END2END_NEARREALTIME_PERFORMANCE.md](../docs/END2END_NEARREALTIME_PERFORMANCE.md)).
6. `viewer_url` in `config.json` drives the first QR code on the last panel (slide 8).
7. **Time zone**: every time on screen is shown in `timezone` (`config.json`,
   `America/Chicago`), whatever the booth machine or a hosted viewer's browser is set to.
   Only the SQL `WHERE time = TIMESTAMP '{init}'` stays in UTC.
8. **Offline backup**: with tiles and SQL up, save a fallback in case the venue has no
   internet:
   ```bash
   uv run presentation/server.py --fetch-offline   # rerun resumes
   uv run presentation/server.py --offline         # no network needed
   ```
   The fetch saves the 3 newest runs (both variables, tiles up to z5), the Carto basemap
   for the same zooms, the fonts and each run's venue SQL results into
   `presentation/offline/` (gitignored). `--offline` replays the saved runs on the demo
   cadence, one landing every 10 min; the header reads REPLAY. The QR codes still point
   online: phones use mobile data. `record_video.sh` records the live page to an MP4 as a
   last resort.

## Hosted on Vercel

The same page, for internal sharing at an unlisted URL. Differences from the booth:

- **SQL is locked.** `/api/config` answers `sql_editable: false`: the editor is read-only,
  Reset is hidden, and the venue chips pick the query. Run sends
  `GET /api/sql?place=<venue>&init=<newest init>`. The function only runs the `config.json`
  query for a `sql.places` entry, and only for an init on the 10-minute grid from the last
  7 days. It rejects anything else, including query text and POSTs. The CDN keeps each
  answer for a day.
- **No pollers.** `/api/state` reads commits and the `time` coordinate on each request and
  the CDN caches it for 5 s with stale-while-revalidate.
- **Tiles go through a caching proxy.** `/api/config` answers `tile_base: /tiles/<repo>`, and
  `vercel.json` rewrites `/tiles/*` to `api/tiles.js` (Node.js, pinned to `iad1`; move it next
  to the tiles service's region once that is known). It forwards only this repo's tiles
  (branch or snapshot id) and keeps successful ones for a day in Vercel's CDN and in the
  Runtime Cache, so viewers share one render per tile. Errors such as a `504` are not
  cached. Tiles are tagged `tiles` and `init-<YYYYMMDDHHMM>`
  (`vercel cache invalidate --tag ...`). The booth's `server.py` fetches tiles straight
  from the tiles service.
- **Windows smaller than 1920 × 1080** show the booth layout zoomed down to fit.
- The vendored libraries are copied into `web/vendor/` at build time (`npm run vendor`).

Vercel project settings: root directory `presentation`, framework preset "Other";
install, build and output directory come from `vercel.json`. Environment variables:

| Variable | Value |
| --- | --- |
| `ARRAYLAKE_API_TOKEN` | read-only token with access to `nvidia/sc26-chicago-stormscope_us-booth`; also the SQL password |
| `ARRAYLAKE_SQL_HOST` | optional, overrides `sql.host` in `config.json` |

Functions may run 60 s (`maxDuration`), enough for a cold SQL service. `vercel.json`
skips deploys of commits that change nothing under `presentation/`.

Check a build locally without deploying anything (in a throwaway copy, since `vercel build`
writes a `pyproject.toml` and `uv.lock` next to `requirements.txt`):

```bash
B=$(mktemp -d) && git -C presentation ls-files -co --exclude-standard | grep -v '^node_modules' \
  | tar -C presentation -cf - -T - | tar -C "$B" -xf -
mkdir "$B/.vercel" && echo '{"projectId":"local","orgId":"local","settings":{"framework":null}}' > "$B/.vercel/project.json"
(cd "$B" && vercel build --yes)
```

## Panels

1. AI weather nowcasting: six observed GOES-19 frames -> twelve AI frames, +120 min.
2. Earth observations: GOES-19 ABI, the two composites with live +0 previews (click to
   switch the globe layer).
3. The AI model: StormScope-US Flash, a distilled diffusion model on the 3 km HRRR grid.
4. The pipeline: Earth2Studio fetch -> predict -> write -> serve.
5. Data flow: stage latencies (fill in from the end-to-end performance doc).
6. Arraylake + Icechunk: overlapped uploads, one atomic commit per run.
7. The data lake: recent commits, time travel.
8. Your turn: viewer and raw-tile QR codes, live SQL over the event venues.

Timestamps are shown in America/Chicago; only the SQL init stays UTC. The strip's
countdown and phase activity are labelled estimates: the API reports publications, not GPU
progress. Diagrams are schematics, not live measurements. SQL reports mean `true_color`
brightness: high means cloudy, low means clear or dark.
