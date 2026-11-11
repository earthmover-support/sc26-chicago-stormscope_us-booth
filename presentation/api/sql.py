"""GET /api/sql on the hosted page: ?place=<name>&init=<...>.

Runs only the config.json query for one of `sql.places`, never free text or coordinates
from the browser: the set of possible URLs stays small (places x inits of the last week),
so the CDN keeps each answer for a day and a stranger cannot make the function run a new
query per request. The CDN caches by exact URL, so a request that is not in the one
canonical form (`?place=..&init=..`, in that order, nothing else) is redirected to it
instead of run: a junk parameter or a swapped order costs one cheap redirect, not one SQL
query. The check compares decoded pairs, not the raw string: Vercel hands the function a
re-encoded query string, so a raw comparison never matched and the redirect pointed at
itself.
"""

import datetime as dt
import re
import sys
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from booth import (  # noqa: E402
    CONFIG,
    fill_init,
    place_queries,
    run_sql_once,
    send_json,
    utcnow,
)

INIT_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:00")
MAX_AGE = dt.timedelta(days=7)


def check_init(init: str) -> str:
    """`init` if it can be a run time: on the run grid, not in the future, at most a week old."""
    if not INIT_RE.fullmatch(init):
        raise ValueError("init must look like YYYY-MM-DDTHH:MM:00")
    t = dt.datetime.fromisoformat(init).replace(tzinfo=dt.UTC)
    if t.minute % CONFIG["run_interval_min"] or not utcnow() - MAX_AGE <= t <= utcnow():
        raise ValueError("init is not a recent run")
    return init


class handler(BaseHTTPRequestHandler):  # noqa: N801 (name the Vercel runtime looks for)
    def do_GET(self):  # noqa: N802
        pairs = parse_qsl(urlsplit(self.path).query, keep_blank_values=True)
        args = dict(pairs)
        if not args:
            return send_json(self, {"status": "idle"})
        queries = place_queries()
        try:
            if args.get("place") not in queries:
                raise ValueError(f"place must be one of {', '.join(queries)}")
            init = check_init(args.get("init", ""))
        except ValueError as exc:
            return send_json(self, {"status": "error", "error": str(exc)}, 400)
        wanted = [("place", args["place"]), ("init", init)]
        if pairs != wanted:
            canonical = urlencode(wanted)
            self.send_response(308)
            self.send_header("Location", f"/api/sql?{canonical}")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", "0")
            return self.end_headers()
        query = fill_init(queries[args["place"]], init)
        try:
            result = run_sql_once(query)
        except Exception as exc:
            return send_json(
                self, {"status": "error", "query": query, "error": str(exc)[:300]}, 502
            )
        send_json(self, result, cache="public, s-maxage=86400")
