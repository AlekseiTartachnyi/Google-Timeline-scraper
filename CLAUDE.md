# CLAUDE.md — Project instructions for AI assistants

## What this project is

ADB-driven scraper that reads Google Maps Timeline from a Pixel phone (English UI)
and exports everything visible on screen to JSON, then to CSV for mileage labeling.

Spec: `timeline-scraper-spec.md`

## How to run

One command per block — copy them one at a time.

Full run: a day to JSON, plus one map screenshot per driving trip.

```
py -m timeline_scraper scrape
```

JSON only, no opening of trip screens.

```
py -m timeline_scraper scrape --no-screenshots
```

Measure how the day list responds to D-pad focus, then exit. Writes dumps and screenshots
to a timestamped `probe-*` folder.

```
py -m timeline_scraper scrape --probe-focus
```

On Windows use `py`, not `python`. The `python` command is intercepted by a Windows
App Execution Alias and redirects to the Microsoft Store.

Output goes to `~/timeline-exports/`:

```
timeline_20260820.draft.json
2026-08-20/1321-1342_driving.png
```

## Who tests what

The phone sits on the user's desk. The AI session has no device, and that is the normal
arrangement, not a defect:

- The AI writes the code and pushes it to the working branch.
- The user pulls the branch, runs it against the real Pixel, and reports what happened.

Never write "I have no phone", "the code was never executed", "untested", or any other
disclaimer of this shape. The user knows — running it is their half of the job, and saying
it back to them wastes the reply.

Say instead what the code is supposed to do and which file or log line settles it. If a
change rests on an assumption the run will confirm or kill, name the assumption and name
the output that answers it.

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

`claude/capture-tap-issue-xteo2h`

The branch name changes with every task. Use the branch named at the end of the reply,
never a remembered one.

Pull the finished work before testing — one command per line:

```
git fetch origin
```

```
git checkout claude/capture-tap-issue-xteo2h
```

```
git pull origin claude/capture-tap-issue-xteo2h
```

If local files look wrong (errors from code you did not write), throw them away:

```
git fetch origin
```

```
git reset --hard origin/claude/capture-tap-issue-xteo2h
```

## Every reply that pushed something ends with the pull commands

Mandatory, not "when it seems useful". The user cannot test what they cannot pull, and the
branch name is different every task.

The last thing in the reply is:

1. The branch name that was actually pushed to.
2. `git fetch origin`, `git checkout <branch>`, `git pull origin <branch>` — **each command
   in its own code block, one command per line**, so each can be copied with one click.
   Never bundle several commands into one block.
3. The run command for whatever is meant to be tested, also in its own block.

Do not assume the previous branch is still current. Read it off the push, do not remember it.

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
| `raw_text` | whole description | also the focus target for the screenshot pass |

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
    adb.py      — adb wrappers: devices, shell, tap, swipe, keyevent, dump_ui, screencap
    nav.py      — launch Maps, navigate to Timeline by accessibility tree text
    model.py    — Visit / Trip / Day dataclasses + JSON serialization
    extract.py  — UI dump -> ordered descriptions, scroll + dedupe, bounds helper
    parse.py    — descriptions -> visits and trips, endpoint linking
    focus.py    — D-pad focus navigation: no coordinates, no taps on the map
    capture.py  — second pass: open each driving trip, wait for the map, screenshot
    probe.py    — measurement run behind `scrape --probe-focus`, writes dumps to disk
    flatten.py  — (M4) JSON -> CSV
```

## Before making any changes

1. Read the relevant source file first
2. Check which milestone the change belongs to
3. Do not implement future milestones — one milestone at a time
4. Verify the change doesn't break M1 by checking cli.py imports and scrape flow
5. Do not run the parser over the user's exported data to "demonstrate" a change —
   testing against real data is the user's job
