# site

A static MapLibre globe of the latest StormScope-US nowcasts over the contiguous US. Tiles
come from the public Arraylake tiles service of the `nvidia` org, branch `main`; on
Vercel through a caching proxy. The page has an init selector, a true color / water vapor
toggle, and playback over lead times. It starts on water vapor while it is dark at the SC26
venue. Playback holds the first frame until all leads have loaded. Every minute it checks
for a new init, loads it in the background, and switches to it once it is complete. No
build step and no server: `index.html`, `sw.js`, three logo SVGs and one Vercel function.

The tiles service URL is `TILES` in `index.html` and `api/tiles.js`.

## Tile cache

The tiles service sends branch tiles with `max-age=0`, so the browser would ask the service
again for every tile it has already seen. `sw.js` is a service worker that answers tile
requests from the browser's Cache API instead, and only goes to the service on a miss.
This is safe because the pipeline publishes each init in a single commit: once an init is
listed, its tiles never change. Only successful responses are stored, and only the newest
12 inits are kept.

Change `CACHE` in `sw.js` (`tiles-v1` → `tiles-v2`) and redeploy if tiles change under the
same URL: an init that was rerun, a reset branch, or a tiles service upgrade that renders
differently. To clear it in one browser: DevTools → Application → Storage → Clear site data.

The tiles service keeps no cache of rendered tiles, so every visitor's browser would make it render the
same tiles of a run again. On Vercel (any `https:` origin) the page asks for `/tiles/...`
instead, which `vercel.json` rewrites to `api/tiles.js`. That function (Node.js, pinned to
`iad1`; move it next to the tiles service's region once known):

- forwards only the page's two kinds of request (tiles and the `_meta` tree of this repo);
- keeps successful responses in two caches: Vercel's CDN (per edge region and hostname) and
  the Runtime Cache, which every region and hostname share because the function always runs
  in one region. Tiles a day, the `_meta` init list 30 s. Errors such as a `504` are not cached;
- merges concurrent misses that land on the same function instance into one tiles-service request;
- tags tiles `tiles` and `init-<YYYYMMDDHHMM>`, so a rerun init can be cleared with
  `vercel cache invalidate --tag init-202611161800`. A redeploy empties the CDN cache too.

Locally (`http:`) the page goes straight to the tiles service.

## Run locally

Serve the folder over HTTP from the repo root:

```bash
uv run --no-project python -m http.server 8765 --directory site
```

Then open http://localhost:8765. The tiles service must be up and public (see
[Viz](../README.md#viz) in the top-level README).

## Hosting

Hosted on Vercel, deployed from `main` with root directory `site`, framework preset "Other"
and no build command. `vercel.json` sets an ignored build step, so Vercel skips deploying
commits that change nothing under `site/`. The tiles service sends
`Access-Control-Allow-Origin: *`, so the page works from any domain.
