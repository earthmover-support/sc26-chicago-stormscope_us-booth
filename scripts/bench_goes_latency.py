"""GOES-19 ABI CONUS latency benchmark (no GPU).

Answers two questions for the data-flow slide:

1. Availability: how long after slot time `T` (and after scan end) is the MCMIPC file
   listed in `noaa-goes19`? From the S3 `last_modified` of every file in the last
   `--hours`, plus a live poll that waits for the next file and records when it shows up.
2. Download: how long does fetching one timestamp take, the way the inference loop does
   it? Raw S3 GET of one MCMIPC file, and Earth2Studio `GOES` (list + download + decode
   the 8 StormScope channels) with the cache off.

Run it in us-east-1 next to the bucket, e.g. on a Coiled CPU VM:

    uv run coiled run --workspace earthmover-devs --region us-east-1 --vm-type m6i.xlarge \
      --container python:3.12-slim --file scripts/ -- bash -c \
      "pip install -q torch --index-url https://download.pytorch.org/whl/cpu \
       && pip install -q earth2studio==0.20.0 && python scripts/bench_goes_latency.py"
"""

from __future__ import annotations

import argparse
import re
import statistics
import time
from datetime import UTC, datetime, timedelta

from obstore.store import S3Store

BUCKET = "noaa-goes19"
PRODUCT = "ABI-L2-MCMIPC"
CHANNELS = ["abi01c", "abi02c", "abi03c", "abi07c", "abi08c", "abi09c", "abi10c", "abi13c"]
NAME_RE = re.compile(r"_s(\d{14})_e(\d{14})_c(\d{14})\.nc$")


def parse_stamp(s: str) -> datetime:
    """GOES file-name time `YYYYJJJHHMMSSt` (day of year, tenths of a second) -> datetime."""
    return datetime.strptime(s[:13], "%Y%j%H%M%S").replace(tzinfo=UTC) + timedelta(
        seconds=int(s[13]) / 10
    )


def slot_of(scan_start: datetime) -> datetime:
    """Nominal 5-min slot `T` of a CONUS scan (start rounded to the nearest 5 min)."""
    t = scan_start + timedelta(minutes=2.5)
    return t.replace(minute=t.minute - t.minute % 5, second=0, microsecond=0)


def hour_prefix(t: datetime) -> str:
    return f"{PRODUCT}/{t:%Y}/{t.timetuple().tm_yday:03d}/{t:%H}/"


def list_files(store: S3Store, now: datetime, hours: float) -> list[dict]:
    """Every MCMIPC file of the last `hours`, with its slot, scan and S3 times."""
    rows = []
    for h in range(int(hours) + 2):
        t = now - timedelta(hours=h)
        for batch in store.list(prefix=hour_prefix(t)):
            for e in batch:
                m = NAME_RE.search(e["path"])
                if not m:
                    continue
                start, end, created = (parse_stamp(g) for g in m.groups())
                if start < now - timedelta(hours=hours):
                    continue
                rows.append(
                    dict(
                        path=e["path"],
                        size=e["size"],
                        slot=slot_of(start),
                        start=start,
                        end=end,
                        created=created,
                        s3=e["last_modified"],
                    )
                )
    return sorted(rows, key=lambda r: r["start"])


def stats(xs: list[float]) -> str:
    xs = sorted(xs)
    p90 = xs[min(len(xs) - 1, int(round(0.9 * (len(xs) - 1))))]
    return (
        f"min {xs[0]:6.1f}  median {statistics.median(xs):6.1f}  p90 {p90:6.1f}  "
        f"max {xs[-1]:6.1f}  (n={len(xs)})"
    )


def report_availability(rows: list[dict]) -> None:
    sec = lambda a, b: [(r[a] - r[b]).total_seconds() for r in rows]  # noqa: E731
    print("\n== Availability from S3 listing (seconds) ==")
    print("scan start   - slot T :", stats(sec("start", "slot")))
    print("scan end     - slot T :", stats(sec("end", "slot")))
    print("created      - slot T :", stats(sec("created", "slot")))
    print("S3 listed    - slot T :", stats(sec("s3", "slot")))
    print("S3 listed    - scan end:", stats(sec("s3", "end")))
    sizes = [r["size"] / 1e6 for r in rows]
    print(f"file size MB          : {stats(sizes)}")


def bench_raw_get(store: S3Store, rows: list[dict], n: int) -> None:
    print(f"\n== Raw S3 GET of one MCMIPC file, {n} newest files (seconds) ==")
    times, rates = [], []
    for r in rows[-n:]:
        t0 = time.perf_counter()
        data = store.get(r["path"]).bytes()
        dt = time.perf_counter() - t0
        times.append(dt)
        rates.append(len(data) / 1e6 / dt)
        print(f"  {r['path'].rsplit('/', 1)[1]}  {len(data) / 1e6:6.1f} MB  {dt:5.2f} s")
    print("GET time s  :", stats(times))
    print("MB/s        :", stats(rates))


def bench_earth2studio(rows: list[dict], n: int) -> None:
    from earth2studio.data import GOES

    print(f"\n== Earth2Studio GOES, one timestamp, 8 channels, cache off, {n} runs (s) ==")
    times = []
    for r in rows[-n:]:
        src = GOES(satellite="goes19", scan_mode="C", cache=False, verbose=False)
        t0 = time.perf_counter()
        da = src(r["slot"].replace(tzinfo=None), CHANNELS)
        dt = time.perf_counter() - t0
        times.append(dt)
        print(f"  slot {r['slot']:%H:%M}  shape {tuple(da.shape)}  {dt:5.2f} s")
    print("fetch time s:", stats(times))


def live_poll(store: S3Store, known: set[str], timeout: float, every: float) -> None:
    """Wait for the next new file; report wall-clock arrival vs slot T and S3 time."""
    print(f"\n== Live poll every {every:.0f} s for the next scan (max {timeout:.0f} s) ==")
    t_end = time.monotonic() + timeout
    while time.monotonic() < t_end:
        now = datetime.now(UTC)
        prefixes = {hour_prefix(now), hour_prefix(now - timedelta(minutes=10))}
        for prefix in prefixes:
            for batch in store.list(prefix=prefix):
                for e in batch:
                    m = NAME_RE.search(e["path"])
                    if m and e["path"] not in known:
                        start, end, _ = (parse_stamp(g) for g in m.groups())
                        slot = slot_of(start)
                        print(f"  new file {e['path'].rsplit('/', 1)[1]}")
                        print(
                            f"  seen at {now:%H:%M:%S}: slot T+{(now - slot).total_seconds():.0f} s, "
                            f"scan end +{(now - end).total_seconds():.0f} s, "
                            f"S3 last_modified +{(now - e['last_modified']).total_seconds():.0f} s"
                        )
                        t0 = time.perf_counter()
                        data = store.get(e["path"]).bytes()
                        dt = time.perf_counter() - t0
                        done = datetime.now(UTC)
                        print(
                            f"  downloaded {len(data) / 1e6:.1f} MB in {dt:.2f} s -> "
                            f"in memory at slot T+{(done - slot).total_seconds():.0f} s"
                        )
                        return
        time.sleep(every)
    print("  no new file before timeout")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--hours", type=float, default=6, help="listing window for availability")
    p.add_argument("--n-get", type=int, default=10, help="files for the raw GET benchmark")
    p.add_argument("--n-e2s", type=int, default=5, help="runs for the Earth2Studio benchmark")
    p.add_argument("--live-timeout", type=float, default=420, help="0 skips the live poll")
    p.add_argument("--poll-every", type=float, default=2)
    args = p.parse_args()

    store = S3Store(BUCKET, region="us-east-1", skip_signature=True)
    now = datetime.now(UTC)
    print(f"now {now:%Y-%m-%d %H:%M:%S} UTC")
    t0 = time.perf_counter()
    rows = list_files(store, now, args.hours)
    print(f"listed {len(rows)} files in {time.perf_counter() - t0:.2f} s")
    report_availability(rows)
    bench_raw_get(store, rows, args.n_get)
    if args.n_e2s:
        bench_earth2studio(rows, args.n_e2s)
    if args.live_timeout:
        live_poll(store, {r["path"] for r in rows}, args.live_timeout, args.poll_every)


if __name__ == "__main__":
    main()
