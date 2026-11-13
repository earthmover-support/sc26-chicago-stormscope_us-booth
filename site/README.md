# site

A static MapLibre globe of the latest StormScope-US nowcasts over the contiguous US, for
phones. The tiles come from branch `main` of the
[Arraylake tiles service](../README.md#tiles-service). On Vercel, they go through the
[tile proxy](../README.md#tile-proxy).

The page has these controls and behaviours:

- An init selector with every init (one per 5 min GOES-19 scan) from the past 24 h.
- A true color / water vapor toggle. The page starts on water vapor while it is dark at
  the SC26 venue (see [Render parameters](../README.md#render-parameters) for why).
- Playback over lead times. Playback holds the first frame until all leads have loaded.
  Each loop then holds +0 for 2 s and holds the last lead for 0.8 + 2 s.
- A check for a new init every minute. The page loads a new init in the background and
  switches to it when it is complete.

There is no server. The folder holds `index.html`, `sw.js`, three logo SVGs and one Vercel
function, `api/tiles.js`. The only build step, `npm run build`, copies the page into `public/`
(what Vercel serves) and MapLibre GL from npm (version pinned in `package.json`) into
`public/vendor/maplibre/`, as the booth page does. The page loads MapLibre from there, not
from a CDN, so no third party can change the script that phones run. Locally:
`npm ci && npm run build`, then serve `public/`.

## Tile cache in the browser

The tiles service sends branch tiles with `max-age=0`. Without help, the browser would ask
the service again for every tile it already has. `sw.js` is a service worker that answers
tile requests from the browser's Cache API. It goes to the service only on a miss.

This is safe because the pipeline publishes each init in a single commit. After an init is
listed, its tiles never change. The service worker stores only successful responses and
keeps only the newest 12 inits.

If tiles change under the same URL, change `CACHE` in `sw.js` (`tiles-v1` to `tiles-v2`)
and redeploy. Tiles change under the same URL after a rerun init, a reset branch, or a
tiles service upgrade that renders differently. To clear the cache in one browser, open
DevTools, then Application, then Storage, and click Clear site data.

The server-side cache that all visitors share is the [tile proxy](../README.md#tile-proxy).

## Run locally

From the repo root, serve the folder over HTTP:

```bash
uv run --no-project python -m http.server 8765 --directory site
```

Then open http://localhost:8765. The tiles service must be up and public (see
[Tiles service](../README.md#tiles-service)).

## Hosting

Vercel deploys the site from `main` with root directory `site`, framework preset "Other"
and no build command. `vercel.json` sets an ignored build step, so Vercel skips commits that
change nothing under `site/`. The tiles service sends `Access-Control-Allow-Origin: *`, so
the page works from any domain.
