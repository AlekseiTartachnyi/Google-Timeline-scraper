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

Run every tap strategy over the same two driving trips and keep what each produced,
then exit. This is the current M2.2 experiment.

```
py -m timeline_scraper scrape --tap-lab
```

On Windows use `py`, not `python`. The `python` command is intercepted by a Windows
App Execution Alias and redirects to the Microsoft Store.

## Folders

Everything is written under `exports/` in the repo root. It is gitignored, so nothing
personal reaches a commit.

```
exports/
    timeline_20260820.draft.json
    2026-08-20/1321-1342_driving.png
    draft-screenshots/
        variant-1-strict-bounds/2026-Aug-24-1503/
        variant-2-anchor-point/2026-Aug-24-1511/
```

Folder and file names are English only. `debug_dumps/` is dead — nothing writes to it any
more; delete it if it is still on the laptop.

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

## What the phone actually is — measured, not assumed

The Timeline day is an `android.webkit.WebView` whose node covers the whole screen:
`[0,0][1080,2410]` on this Pixel. The map and the list are both inside that one web page.

Two things follow, and both were paid for once already:

- **D-pad focus does not work.** A focus walk leaves the WebView on its first step and
  stops on a chrome button ("Backup enabled."). Nothing in the list can be selected before
  it is activated. Touch is the only way in.
- **The full-screen WebView is useless as a bounding box.** Rows are virtual accessibility
  nodes of the web page. Their rectangles are the only positional information available,
  and they cannot be checked against a container, because the container is the screen.

Do not re-propose focus navigation, and do not assume a row rectangle is where the row is.

## Never propose the Timeline export

Google Takeout, "Export Timeline data", the emailed archive — all of it is settled and the
answer is no. The export arrives by email and cannot be matched back to what the map shows,
which is the entire point of this tool. It has been raised in several sessions and refused
in every one. Do not raise it again.

## Current milestone status

- [x] M1 — ADB preflight, wake screen, launch Maps, navigate to Timeline
- [x] M2.1 — Open a chosen day through the Timeline calendar
- [~] M2.2 — One day -> JSON works. The map screenshot per driving trip does not:
      the touch misses the row. `scrape --tap-lab` is measuring which strategy lands.
- [ ] M2 — Output path prompt, timestamped filename, overwrite/rename/cancel
- [ ] M3 — Scrape 7 days with crash-safe incremental save
- [ ] M4 — Flatten to CSV
- [ ] M5 — Full month export
- [ ] M6 — Polish: interactive prompts, logging, tests

## How branches are named

`task-<NN>-<YYYY>-<Mon>-<DD>`, for example `task-07-2026-Aug-24`.

- `NN` is the task number, zero-padded, one higher than the largest `task-*` branch already
  on the remote. Check with `git branch -r` before naming a new one.
- The date is the day the branch was created, month as a three-letter English abbreviation.

No mood words, no generated nonsense, no milestone names. If a task harness hands over a
branch name that does not follow this, say so in the reply and use the one it gave — never
push to a name the user has not been told about.

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
- Never suggest the Google Timeline / Takeout export as a data source

## Project structure

```
src/timeline_scraper/
    cli.py      — argparse entrypoint (scrape / flatten)
    adb.py      — adb wrappers: devices, shell, tap, swipe, keyevent, dump_ui, screencap
    nav.py      — launch Maps, navigate to Timeline by accessibility tree text
    model.py    — Visit / Trip / Day dataclasses + JSON serialization
    extract.py  — UI dump -> ordered descriptions, scroll + dedupe, bounds helper
    parse.py    — descriptions -> visits and trips, endpoint linking
    tap.py      — where to touch a row: two strategies, two gestures
    capture.py  — second pass: open each driving trip, wait for the map, screenshot
    taplab.py   — `scrape --tap-lab`: runs every strategy and keeps what each produced
    flatten.py  — (M4) JSON -> CSV
```

## Before making any changes

1. Read the relevant source file first
2. Check which milestone the change belongs to
3. Do not implement future milestones — one milestone at a time
4. Verify the change doesn't break M1 by checking cli.py imports and scrape flow
5. Do not run the parser over the user's exported data to "demonstrate" a change —
   testing against real data is the user's job
