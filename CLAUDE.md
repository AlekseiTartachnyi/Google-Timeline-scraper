# CLAUDE.md — Project instructions for AI assistants

## What this project is

ADB-driven scraper that reads Google Maps Timeline from a Pixel phone (English UI)
and exports everything visible on screen to JSON, then to CSV for mileage labeling.

Spec: `timeline-scraper-spec.md`

## How to run

```
py -m timeline_scraper scrape                  # day -> JSON + one map screenshot per drive
py -m timeline_scraper scrape --no-screenshots # JSON only, no taps into trip screens
```

On Windows use `py`, not `python`. The `python` command is intercepted by a Windows
App Execution Alias and redirects to the Microsoft Store.

Output goes to `~/timeline-exports/`:

```
timeline_20260820.draft.json
2026-08-20/1321-1342_driving.png
```

## Current milestone status

- [x] M1 — ADB preflight, wake screen, launch Maps, navigate to Timeline
- [x] M2.1 — Open a chosen day through the Timeline calendar
- [x] M2.2 — One day -> JSON: trip endpoints + map screenshot per driving trip
- [ ] M2 — Output path prompt, timestamped filename, overwrite/rename/cancel
- [ ] M3 — Scrape 7 days with crash-safe incremental save
- [ ] M4 — Flatten to CSV
- [ ] M5 — Full month export
- [ ] M6 — Polish: interactive prompts, logging, tests

## Working branch

`claude/m2-2-missing-geotags-dmajw0`

Pull the finished work before testing — the branch name changes per task, so always
check the branch named in the reply, not a remembered one:

```
git fetch origin
git checkout claude/m2-2-missing-geotags-dmajw0
git pull origin claude/m2-2-missing-geotags-dmajw0
```

If local files seem wrong (errors from code you didn't write), throw them away:

```
git fetch origin
git reset --hard origin/claude/m2-2-missing-geotags-dmajw0
```

When a task is finished, the reply must end with the exact pull command for the branch
it was pushed to. Do not assume the previous branch is still current.

## What to extract

Per day, in screen order. A row that is not one of these is chrome and is dropped.

**Visit** — a stop.

| field | from the row | notes |
|---|---|---|
| `place` | head of the description | `Visited X?` -> `X` + `unconfirmed: true` |
| `address` | text after the time range | may be absent |
| `start_time` / `end_time` | `9:13 AM – 1:21 PM` | `Left at` sets end only, `Arrived at` sets start only |
| `unconfirmed` | `Visited X?` | Google is guessing the place |
| `missing` | `Missing visit` | Google knows there was a stop, not where |
| `raw_text` | whole description | never dropped |

**Trip** — a movement segment (`Driving`, `Walking`, `Missing travel`, transit modes).

| field | from the row | notes |
|---|---|---|
| `mode` | head of the description | |
| `start_time` / `end_time` | `1:21 PM – 1:42 PM` | |
| `duration_min` | `21 min`, `1 hr 5 min` | |
| `distance_mi` | `4.0 mi`, `500 ft`, `3 km` | Google's GPS track length, not the route |
| `from_place` / `from_address` | the visit **before** | only if `visit.end_time == trip.start_time` |
| `to_place` / `to_address` | the visit **after** | only if `visit.start_time == trip.end_time` |
| `screenshot` | second pass | driving trips only |
| `raw_text` | whole description | also the tap target for the screenshot pass |

Rules that must not be relaxed:

- A trip row never contains an address. Endpoints come from the neighbouring visits.
- Clock strings must match exactly. No tolerance window, no nearest-neighbour guess.
- No match, or the neighbour is a `Missing visit` -> endpoint stays `null`. Never invent
  an address: this data ends up in a tax record.
- Action rows (`Yes`, `No`, `Edit`, `Add travel`, `Add visit`, `Delete`) repeat the row
  above them and are dropped before linking, or one visit becomes three rows.
- Distances are recorded as reported. Correcting them is a separate, deferred task
  (spec §9.4) that keeps both numbers.

## Key rules (from spec)

- English only — no Russian in code, comments, commits, or docs
- No personal data committed — exports live outside the repo
- Use `py` not `python` on Windows
- Do not use `ZoneInfo` without adding `tzdata` to pyproject.toml dependencies
  (Windows has no built-in timezone database)
- Test fixtures must be anonymized
- No autonomous agents — two deterministic commands only: `scrape` and `flatten`

## Project structure

```
src/timeline_scraper/
    cli.py      — argparse entrypoint (scrape / flatten)
    adb.py      — adb wrappers: devices, shell, tap, swipe, dump_ui, wake_screen, is_locked
    nav.py      — launch Maps, navigate to Timeline by accessibility tree text
    model.py    — Visit / Trip / Day dataclasses + JSON serialization
    extract.py  — UI dump -> ordered descriptions, scroll + dedupe, bounds helper
    parse.py    — descriptions -> visits and trips, endpoint linking
    capture.py  — second pass: open each driving trip, wait for the map, screenshot
    flatten.py  — (M4) JSON -> CSV
```

## Before making any changes

1. Read the relevant source file first
2. Check which milestone the change belongs to
3. Do not implement future milestones — one milestone at a time
4. Verify the change doesn't break M1 by checking cli.py imports and scrape flow
5. Do not run the parser over the user's exported data to "demonstrate" a change —
   testing against real data is the user's job
