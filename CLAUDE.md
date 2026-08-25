# CLAUDE.md — Project instructions for AI assistants

## What this project is

ADB-driven scraper that reads Google Maps Timeline from a Pixel phone (English UI)
and exports everything visible on screen to JSON, then to CSV for mileage labeling.

Spec: `timeline-scraper-spec.md`

## How to run

One command per block — copy them one at a time.

Scrape the day: driving and missing travel to JSON, plus the numbered report, which is
also printed to the console.

```
py -m timeline_scraper scrape
```

With no flags this scrapes the seven days ending on the M3 test day, 2026-Aug-20. Another
range is `--start YYYY-MM-DD --end YYYY-MM-DD`; a single day is the same date in both.

On Windows use `py`, not `python`. The `python` command is intercepted by a Windows
App Execution Alias and redirects to the Microsoft Store.

## Folders

Everything is written under `exports/` in the repo root. It is gitignored, so nothing
personal reaches a commit.

```
exports/
    timeline_2026-Aug-20_15-30.json    driving and missing travel, endpoints resolved
    timeline_2026-Aug-20_15-30.txt     the same day as the numbered report
```

The date is the day that was scraped; `_HH-MM` is when it was collected. Google keeps
revising a day for a while after it happens, so a second scrape of the same day must not
overwrite the first — every draft keeps its own name.

A finished multi-day export (M3 onward) is named for its range and carries no collection
time, because it is the settled result and a re-run replaces it:

```
exports/
    timeline_2026-Aug-14 - 2026-Aug-20.json    every day of the range, in date order
    timeline_2026-Aug-14 - 2026-Aug-20.txt     the same range as the numbered report
```

A screen that defeats the navigation is saved next to the export as
`dump_calendar-not-found_2026-Aug-15_11-22-33.xml` (or `dump_day-cell-not-found_...`),
and the file name is printed in the error. That dump is what settles the next fix.

While a range is being collected the same name carries a `.partial.json` suffix. It is
rewritten after every scraped day and deleted when the range finishes, so an interrupted
run keeps what it already read off the screen; re-running the same command resumes from
there and retries the days that failed.

Both names are built in `naming.py`. Months come from a table there, never from
`strftime('%b')`, which follows the laptop's regional setting.

Folder and file names are English only. `debug_dumps/` and `draft-screenshots/` are dead —
nothing writes to them any more; delete them if they are still on the laptop.

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

Measured, therefore settled:

- **D-pad focus does not work.** A focus walk leaves the WebView on its first step and
  stops on a chrome button ("Backup enabled."). Nothing in the list can be selected before
  it is activated. Touch is the only way in. Do not re-propose focus navigation.
- **Rows are virtual accessibility nodes of a web page**, not Android views.
- **Once a day is open, the calendar chip is gone.** After a day is selected the screen
  carries no "Today" label and nothing clickable that reads like a date, so the calendar
  cannot be reopened from there. Measured on 2026-Aug-25: the first day scraped fine and
  the six after it all failed with "Calendar control not found". Every day is therefore
  reached from a freshly launched Maps — force-stop, launch, Timeline, calendar — which is
  the one path known to work.

Not measured, therefore not to be asserted:

- whether a scrollable node exists *inside* the WebView. The day list scrolls, so something
  scrolls it; whether that something appears in the tree as its own node with its own
  rectangle has never been read off a dump.
- whether a row's reported rectangle is wrong, stale, or correct-but-misused. This decides
  the whole fix and is still unknown.

The one dump that answers both is the day screen's full tree next to the screenshot taken
at the same moment. Ask for it rather than reasoning around it.

## The per-trip map screenshot is parked

Opening each driving trip to screenshot its map was tried and abandoned: the touch lands on
the map instead of the row, and the WebView gives nothing reliable to aim at. The code for
both tap strategies is in commit `88e7956` if it is ever picked up again. Until then the
map is checked by hand, and the scraper's job stops at the JSON and the report.

## Never propose the Timeline export

Google Takeout, "Export Timeline data", the emailed archive — all of it is settled and the
answer is no. The export arrives by email and cannot be matched back to what the map shows,
which is the entire point of this tool. It has been raised in several sessions and refused
in every one. Do not raise it again.

## Current milestone status

- [x] M1 — ADB preflight, wake screen, launch Maps, navigate to Timeline
- [x] M2.1 — Open a chosen day through the Timeline calendar
- [x] M2.2 — One day -> JSON and a numbered report: driving and missing travel only,
      endpoints resolved, missing visits named as such
- [ ] M2 — Output path prompt, timestamped filename, overwrite/rename/cancel
- [x] M3 — Scrape 7 days with crash-safe incremental save
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

`claude/task-m3-plan-bjjih9`

The branch name changes with every task. Use the branch named at the end of the reply,
never a remembered one.

Pull the finished work before testing — one command per line:

```
git fetch origin
```

```
git checkout claude/task-m3-plan-bjjih9
```

```
git pull origin claude/task-m3-plan-bjjih9
```

If local files look wrong (errors from code you did not write), throw them away:

```
git fetch origin
```

```
git reset --hard origin/claude/task-m3-plan-bjjih9
```

## When to print the git commands

**The first push to a branch** — print the branch name and the full set, each command in its
own code block, one command per line, never bundled:

`git fetch origin`, `git checkout <branch>`, `git pull origin <branch>`.

**Every push after that, same branch, same session** — the checkout already happened. One
command is enough:

`git pull origin <branch>`

Repeating the full set on every reply is noise. Print it again only when the branch changes.

Always print the run command for whatever is meant to be tested, in its own block.

Do not assume a remembered branch is still current. Read it off the push.

## Ask instead of assuming

Anything about how the phone behaves — what is in the tree, where a container ends, what a
gesture does, how many taps a row needs — is a measurement. It cannot be derived from the
source, and guessing at it has already cost this project two rebuilds.

When a device fact is needed and not known: ask for the dump, the screenshot, or the log
line that settles it, and say exactly which file. Do not state a device fact confidently
because it seems likely, and do not write code whose correctness depends on one.

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
| `from_missing` / `to_missing` | the neighbour is a `Missing visit` | Google knows a stop was there, not where |
| `raw_text` | whole description | never dropped |

Only `Driving` and `Missing travel` reach the output. Walking and the transit modes are
parsed — they are needed to keep the row order intact — and then dropped, because they are
not driven and never reach a mileage record. Endpoints are linked over the full segment
list first, so a visit sitting between a walk and a drive still supplies its address.

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
    naming.py   — export file names and the report's date header, English month table
    report.py   — a day rendered as the numbered list checked by eye
    flatten.py  — (M4) JSON -> CSV
```

## Before making any changes

1. Read the relevant source file first
2. Check which milestone the change belongs to
3. Do not implement future milestones — one milestone at a time
4. Verify the change doesn't break M1 by checking cli.py imports and scrape flow
5. Do not run the parser over the user's exported data to "demonstrate" a change —
   testing against real data is the user's job
