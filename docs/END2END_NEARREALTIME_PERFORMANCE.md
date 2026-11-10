# End-to-end near-real-time performance

How long it takes from GOES-19 scanning the contiguous US to the forecast playing on the
booth screen, stage by stage. `T` is the nominal 10-minute slot time, which the pipeline
uses as the forecast init time.

**Method.** The starting point is the GTC Berlin StormScope-EU booth setup migrated to the
US as is (the first three commits of this repo): same pipeline structure, store layout,
booth page and mobile viewer, with GOES-19 / StormScopeGOES `3km_10min_flash` swapped in.
That is the **baseline**. Every change after that is measured on its own, before and after,
and logged in [Improvements](#improvements) with the stage it moves, so the gain of each
change is known separately. Update the `current` column only from a logged measurement.

## Stages

| # | stage | description | baseline | current | notes |
|---|---|---|---|---|---|
| 1 | Scan | GOES-19 ABI scans the CONUS sector every 5 min (mode 6). The scan for slot `T` starts at `T`+1:17 and ends at `T`+3:54. | 3.9 min | 3.9 min | instrument; nothing to tune |
| 2 | On NOAA's S3 bucket | The L2 MCMIPC file (all 16 channels as CMI: reflectance / brightness temperature) is created at `T`+4:06 and listed in `noaa-goes19` at `T`+4:18 (median; p90 `T`+4:27, max `T`+4:37; n=71). | 0.4 min after scan end | 0.4 min | NOAA side. Public, no licence gate (the EU setup waited 48 min here). |
| 3 | Pickup | The pipeline lists the bucket every `--wait-seconds` (default 15 s) and starts on the newest 10-min slot whose 6 input frames (`T`-50 … `T`) are all listed. | ≤ 15 s | | |
| 4 | Download + regrid | `fetch_data` pulls 6 MCMIPC files (only the newest is new per cycle; the others are in the earth2studio cache) and the model regrids them from the GOES fixed grid to the 3 km HRRR grid (nearest neighbour). One new timestamp from us-east-1: raw S3 GET of the 56 MB file 0.57 s (~99 MB/s); Earth2Studio `GOES` list + download + decode of the 8 channels 1.2 s (median, max 1.5 s). Regrid not yet measured. | download 1.2 s; regrid TBD | fetch 1.3 s (`FrameCache`) | |
| 5 | Inference + ingest | StormScopeGOES Flash rolls forward 12 × 10 min. Each step's `true_color` / `water_vapor` composites upload to Icechunk in the background while the next step runs; one commit after the last step publishes the whole init. The pipeline prints `timing: fetch …, rollout+write …, commit …` per run. Measured on 1x L40S (`g6e.xlarge`, us-east-1): fetch ~6 s, 12 × ~4 s rollout+write, commit ~1 s. | 46–56 s | 41.7 s | fetch includes stage 4 |
| 6 | Visible to tiles service | The tiles service reads Icechunk directly, so a commit is renderable as soon as it lands. | 0 s | | |
| 7 | Discovered by client | Booth page: `server.py` polls Arraylake every 5 s, the browser polls `/api/state` every 4 s. Phone viewer: re-reads the init list every 60 s. | ≤ 9 s (phone ≤ 60 s) | | |
| 8 | First frame rendered | Tiles service renders the home-view tiles of lead 0. | TBD | | depends on the `nvidia` tiles service region and replicas |
| 9 | Full run rendered | All 13 leads loaded in one browser, 3 leads in flight. | TBD | | |
| | **Total** | slot time `T` → full run playing on the booth screen | **TBD** | | |

Stages 1–2 bound how fresh any run can be: the newest init is usable from about `T`+4.3 min.

## Improvements

One row per change, measured before and after on the same setup. Link the PR.

| date | change | stage(s) | before | after | PR |
|---|---|---|---|---|---|
| 2026-11-09 | baseline: Berlin setup migrated to US | all | – | see Stages | c226415, 25a10ee, 4e19d47 |
| 2026-11-10 | keep decoded GOES frames in memory between inits (`FrameCache`); only the newest file is read | 4, 5 | fetch 4.1 s (1 new + 5 cached files decoded again) | fetch 1.3 s (1 new + 5 from memory) | [#1](https://github.com/earthmover-support/sc26-chicago-stormscope_us-booth/pull/1) |

Candidates, not yet measured:

- Run every 5 min instead of every 10: CONUS scans every 5 min and the model only needs its
  inputs 10 min apart, so an init on every 5-min slot halves the wait for the next run
  (needs `floor_to_slot` on a 5-min grid and the booth's `run_interval_min`).
- `--region`: a smaller Flash domain (`set_domain`) for fewer pixels per step.
- Co-locate GPU, Arraylake bucket and tiles service in us-east-1 (NOAA's bucket is in
  us-east-1 as well).

## Sources and reproduce

- Stages 1–2: scan start/end and creation time from the file names
  (`OR_ABI-L2-MCMIPC-M6_G19_s…_e…_c….nc`) and the S3 `last_modified` of the last 22 files
  in `noaa-goes19/ABI-L2-MCMIPC/`, listed with `obstore` on 2026-11-09 19:51 UTC: S3 time
  minus scan start min / median / max = 180 / 181 / 200 s; scan start `T`+77 s. The same
  listing is what `latest_goes_slot` in `scripts/stormscope_us_pipeline.py` uses.
- Stage 2 (n=71) and stage 4 download: `scripts/bench_goes_latency.py` on a Coiled CPU VM
  (m6i.xlarge, us-east-1, `python:3.12-slim` + earth2studio 0.20.0) on 2026-11-09 20:16 UTC.
  Last 6 h of files: S3 listed minus slot `T` min / median / p90 / max = 256 / 258 / 267 /
  277 s, minus scan end 21 / 24 / 33 / 42 s. Live poll every 2 s: the 20:15 scan was seen
  at `T`+270 s, 1 s after its S3 `last_modified`, and was in memory at `T`+271 s.
  Download of one timestamp: raw GET 0.56–0.57 s for 56 MB (10 files); Earth2Studio
  `GOES(cache=False)` for the 8 StormScope channels 1.18–1.50 s (5 runs). From a laptop in
  Europe the same GET takes 54 s, so the pipeline must run in us-east-1.
- `FrameCache` (stages 4–5): `main` then `frame-cache`, 3 inits each, back to back on one
  Coiled `g6e.xlarge` (us-east-1, L40S, `--publish-target local`) on 2026-11-10. Init
  15:30 on `main` and 15:35 on `frame-cache` decode 5 files from the disk cache: fetch 4.1 /
  3.5 s. Init 15:40 on `frame-cache` reuses the 5 frames of init 15:30 from memory: fetch
  1.3 s, total 41.7 s. An init reuses frames from the init 10 min earlier, so the first two
  inits after a start read every file.
