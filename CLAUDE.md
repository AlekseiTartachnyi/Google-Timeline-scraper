# CLAUDE.md — Project instructions for AI assistants

## What this project is

ADB-driven scraper that reads Google Maps Timeline from a Pixel phone (English UI)
and exports everything visible on screen to JSON, then to CSV for mileage labeling.

Spec: `timeline-scraper-spec.md`

## How to run

One command per block — copy them one at a time.

**One command does the whole job.** It walks the days on the phone, writes the JSON and the
numbered report, then the mileage sheet, and fills the sheet's two route columns from the
Google Routes API:

```
py -m timeline_scraper scrape --month 2026-07 --routes
```

`--month` names both ends of the range, so `--start` and `--end` are refused beside it. With
no flags at all the scrape covers the seven days ending on the M3 test day, 2026-Aug-20;
another range is `--start YYYY-MM-DD --end YYYY-MM-DD`, and a single day is the same date in
both. `--out PATH` puts the files somewhere other than `exports/`.

Drop `--routes` and everything else still happens — the JSON, the report and the CSV — with
the two route columns left empty. Nothing is asked of Google and nothing is billed.

```
py -m timeline_scraper scrape --month 2026-07
```

The month is walked day by day, so it resumes the same way as any other range: re-running the
same command picks up where an interrupted run stopped and retries the days that failed.
Google's calendar opens on the month of the day already showing, and the first day of the run
is what walks it back to July.

The first run with `--routes` and no key creates `api-keys.txt` in the project folder and
stops. Open it, paste the key after `routes_api_key =`, save, run the command again. That is
the whole setup, once — the file is gitignored, so it stays on the laptop and never reaches a
commit. A `GOOGLE_MAPS_API_KEY` environment variable still works and is read second. The key
is checked before the phone is driven, so a missing one costs seconds, not a whole run.

Every new pair of addresses is one billed Routes API call per toll setting, so two per trip;
the answers are cached in `exports/route-cache.json` and never asked for twice.

## Photographing the days

A separate command, and a separate kind of output. It drives the phone the same way the
scrape does — Maps, Timeline, the calendar for the first day, the day bar's arrow for every
day after it — and saves every screenful of every day exactly as the phone drew it. Nothing
is parsed, nothing is asked of Google, nothing is billed:

```
py -m timeline_scraper shots --start 2026-08-30 --end 2026-09-05
```

This is the picture the sheet was read off. The sheet is what gets added up and argued
about; the screens are what shows the numbers were not invented, which is the whole reason
to have them when the reader is an insurer rather than an accountant.

`shots` has no default range. A scrape with the dates wrong costs a re-run; a folder of
screenshots handed to somebody under the wrong week is worse than none, so the days are
spelled out or the command refuses. The same date in both flags is one day, and
`--month 2026-08` is a whole month. `--out PATH` puts the folder somewhere other than
`exports/`.

Re-running the same command resumes: days already photographed are skipped, days that
failed are retried, and whatever a half-finished day left on disk is deleted before that day
is tried again. A day the phone never confirmed the date of keeps its screens, named
`_unconfirmed` — check those by eye before anyone else sees them.

A day does not fit on one screen, so a day is a numbered series of screens. Consecutive
screens overlap by more than half, because the swipe that walks the day is the one measured
to work on this phone (`extract.scroll_step`, 80% of the screen up to 35%) and is not worth
trading for fewer files. The images are never edited — a screenshot that has been drawn on
stops being evidence of anything — so the date, which scrolls away with the list after the
first screen, is carried by the file name and by `index.txt`.

Make the sheet again from an export that already exists, without touching the phone. With no
flags it takes the newest finished export in `exports/` and writes the CSV beside it, under
the same name:

```
py -m timeline_scraper flatten
```

Another file is `--in "exports/timeline_2026-Jul.json"` — quote the name if it has spaces in
it, as a range export does — and `--out PATH` names the CSV. `--routes` fills the two route
columns, the same lookups the scrape does.

Price a sheet again after editing it by hand. This reads the addresses out of the CSV, not
out of the JSON, so corrected addresses and deleted rows are what gets sent:

```
py -m timeline_scraper routes --in "exports/timeline_2026-Aug-14 - 2026-Aug-20.csv"
```

With no `--in` it takes the newest CSV in `exports/`. It writes back into the same file;
`--out PATH` puts the result somewhere else and leaves the original alone. Every routable
row is asked about again rather than only the empty ones — the point of running it is that
the addresses changed, and a number left over from the address that used to be in that cell
is worse than an empty cell. Pairs already in the cache cost nothing.

`routes` does not share its cached answers with the `--routes` flag. Measured: the flag
sends the address alone, `1 A St, Austin TX`, while `routes` sends the whole cell,
`Home, 1 A St, Austin TX` — different text, different cache key, so running `routes` over a
sheet the flag already filled buys the month a second time even if nothing was edited. Both
are deliberate (a place name is a label this phone made up; an edited cell is the user's own
text), so: the flag while the addresses are as scraped, `routes` only after they have been
corrected by hand.

On Windows use `py`, not `python`. The `python` command is intercepted by a Windows
App Execution Alias and redirects to the Microsoft Store.

`adb` has to be reachable. Normally it is on PATH; a terminal that does not carry it is
told where to look instead — one command, then the scrape in the same window:

```
set ADB=C:\platform-tools\adb.exe
```

The run says which adb it used when it is not the one on PATH.

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
    timeline_2026-Aug-14 - 2026-Aug-20.csv     the mileage sheet, one row per drive
    route-cache.json                           routed miles already paid for
```

A range that is exactly one calendar month, first day to last, is named for the month and
nothing else — spelling both ends out only makes the name longer than the thing it names:

```
exports/
    timeline_2026-Jul.json
    timeline_2026-Jul.txt
    timeline_2026-Jul.csv
```

The name comes from the range, not from the flag that asked for it, so `--month 2026-07`
and the two dates spelled out resume the same partial file and replace the same export.

Screenshots go in a folder of their own, named for the same range and never mixed in with
the files that carry numbers:

```
exports/
    screens_2026-Aug-30 - 2026-Sep-05/
        2026-Aug-30_Sun_01.png     the first screen of the day, the one with the date on it
        2026-Aug-30_Sun_02.png     and down the day from there
        2026-Sep-03_Thu_01_unconfirmed.png    the phone never named this date
        index.json                 what the next run resumes from
        index.txt                  what each day holds, for whoever opens the folder
```

`route-cache.json` is keyed by the addresses that were driven between, so it is personal
data and lives with the exports, outside the repo. Deleting it costs money, not correctness:
the next `--routes` run asks Google again.

The CSV is derived from the JSON and carries no collection time either. The scrape writes it
at the end of the run, and `flatten` writes it again from the same export; either way a
re-run replaces it.

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
- **The date chip scrolls away with the list.** Measured on 2026-Aug-25: the first day
  scraped fine and the six after it failed with "Calendar control not found". Collecting a
  day leaves the list at the bottom, and at the bottom the tree carries no date row at all
  — the chip is part of the same web page, not Android chrome. The day does not go
  anywhere and the calendar is still reachable; the list has to be swiped back to its
  first row before anything in the app bar can be tapped.
- **The day has a bar of its own: `‹ Tue, Aug 11, 2026 ▾ ›`.** The date names the open
  day — the log read `Day 2026-08-15 is showing: 'Sat, Aug 15, 2026'` — the arrows either
  side step one day, and tapping the date opens the month calendar. So the calendar is
  needed once, for the first day of a run; every day after it is one tap on the right
  arrow. The calendar stays as the fallback for when the arrows are not there or do not
  move the day.
- **A row is not clickable to be tappable.** These are virtual web nodes: the node holding
  the label and the node holding the click handler are not the same, so requiring
  `clickable="true"` throws away the chip. Taps go to coordinates; what keeps the wrong
  thing from being tapped is position plus checking afterwards that the calendar opened.

Not measured, therefore not to be asserted:

- whether a scrollable node exists *inside* the WebView. The day list scrolls, so something
  scrolls it; whether that something appears in the tree as its own node with its own
  rectangle has never been read off a dump.
- whether a row's reported rectangle is wrong, stale, or correct-but-misused. This decides
  the whole fix and is still unknown.
- **how the calendar moves between months.** Named arrows, a sideways page, a scrolling list
  of months — none of it has been read off a dump, and the picker is part of the same web
  page as the day list, so an Android date picker's behaviour says nothing about it. The
  code therefore tries a named control, then a sideways swipe, then a swipe along the page,
  and judges each by the months the screen shows afterwards: the one that moves the calendar
  toward the target is kept for the rest of the walk, one that moves it the wrong way is
  reversed, one that moves nothing is dropped. The log line `The calendar reached 2026-07 by
  a sideways swipe` is what settles which it actually is; a failed walk saves the screen as
  `dump_month-not-reached_...xml`.

The one dump that answers both is the day screen's full tree next to the screenshot taken
at the same moment. Ask for it rather than reasoning around it.

## The per-trip map screenshot is parked — that is not what `shots` does

Opening each driving trip to screenshot its map was tried and abandoned: the touch lands on
the map instead of the row, and the WebView gives nothing reliable to aim at. The code for
both tap strategies is in commit `88e7956` if it is ever picked up again. Until then the
map is checked by hand, and the scraper's job stops at the JSON and the report.

What failed there was the tap that opens one trip, not the screenshot. `adb.screencap` has
worked every time it has been asked. `shots` never taps into a row — it photographs the day
list as it scrolls past — so it is not the parked work and does not inherit its defect.

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
- [x] M4 — Flatten to CSV (no tests here — they are M6)
- [ ] M5 — Full month export (`--month`, the calendar walked across months, the sheet written
      by the scrape itself; waiting on a July run)
- [ ] M6 — Polish: interactive prompts, logging, tests

Beside the milestones, not one of them:

- [x] `shots` — every day photographed screen by screen, for showing alongside the sheet

## How branches are named

`task-<NN>-<YYYY>-<Mon>-<DD>`, for example `task-07-2026-Aug-24`.

- `NN` is the task number, zero-padded, one higher than the largest `task-*` branch already
  on the remote. Check with `git branch -r` before naming a new one.
- The date is the day the branch was created, month as a three-letter English abbreviation.

No mood words, no generated nonsense, no milestone names. If a task harness hands over a
branch name that does not follow this, say so in the reply and use the one it gave — never
push to a name the user has not been told about.

## Working branch

`claude/compassionate-noether-3x4fpt`

The branch name changes with every task. Use the branch named at the end of the reply,
never a remembered one.

Pull the finished work before testing — one command per line:

```
git fetch origin
```

```
git checkout claude/compassionate-noether-3x4fpt
```

```
git pull origin claude/compassionate-noether-3x4fpt
```

If local files look wrong (errors from code you did not write), throw them away:

```
git fetch origin
```

```
git reset --hard origin/claude/compassionate-noether-3x4fpt
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

## The mileage sheet

The sheet has ten columns and nothing else — written by the scrape at the end of a run, and
again by `flatten` from an export that already exists:

```
date, weekday, from_address, departure_time, to_address, arrival_time,
miles, Tolls, No tolls, mode
```

- `date` reads `2026, Aug 28`: the year first, the month by name, the day padded so the
  column stays a column. `07/08` does not say which half is the month, and this sheet is
  filed by year.
- `weekday` is the three-letter English day, `Fri`. A mileage record is argued about in
  weekdays — the Saturday drive to a job site is the one that gets asked about — and
  counting them off a column of dates is work nobody should have to repeat.
- `mode` is last, past the miles: `Driving`, or `Missing travel` where Google recorded
  travel it could not describe. Those rows stay in the sheet, in the day they belong to —
  a visible hole is what catches a drive Maps failed to log.
- An endpoint reads `place, address` when both are known, and `Missing visit` when Google
  recorded a stop it could not name.
- **A cell the scrape could not fill says `missing information`**, never blank: a row that
  needs hand work must not read as a row that is simply short. The one exception is `miles`,
  which stays empty so the column can still be added up — the mode beside it already says
  why the number is not there.
- Each day is followed by a blank line, so the days stay apart down the screen.
- `miles` is Timeline's own number — the length of the recorded GPS track. `Tolls` and
  `No tolls` are what the road network says between the same two addresses, with tolls
  allowed and with tolls avoided; they stay empty until the routes are looked up. Both numbers are kept and neither is corrected into the other
  (spec §9.5): a detour is legitimate, so a track longer than the route is a row to
  review, not an error.
- **A drive across midnight is written once.** Google lists it on both days with the same
  distance and no clock strings at all, which would claim the miles twice; the copy on the
  second day is dropped and named in the log. Its times and endpoints still come out as
  `missing information` — parsing that row is still open (spec §9.4) — so it needs
  completing by hand.

## Key rules (from spec)

- English only — no Russian in code, comments, commits, or docs
- No personal data committed — exports live outside the repo
- The API key lives in `api-keys.txt` in the project folder, gitignored. Never in the
  source, never in a commit, never typed into a chat
- Use `py` not `python` on Windows
- Do not use `ZoneInfo` without adding `tzdata` to pyproject.toml dependencies
  (Windows has no built-in timezone database)
- Test fixtures must be anonymized
- No autonomous agents — four deterministic commands only: `scrape`, `shots`, `flatten`,
  `routes`
- Never suggest the Google Timeline / Takeout export as a data source

## Project structure

```
src/timeline_scraper/
    cli.py      — argparse entrypoint (scrape / flatten / routes)
    adb.py      — adb wrappers: devices, shell, tap, swipe, keyevent, dump_ui, screencap
    nav.py      — launch Maps, navigate to Timeline by accessibility tree text
    model.py    — Visit / Trip / Day dataclasses + JSON serialization
    extract.py  — UI dump -> ordered descriptions, the measured scroll, bounds helper
    shots.py    — a day photographed screen by screen, and the folder's index
    parse.py    — descriptions -> visits and trips, endpoint linking
    naming.py   — export file names and the report's date header, English month table
    report.py   — a day rendered as the numbered list checked by eye
    flatten.py  — JSON -> the mileage CSV, one row per drive; route columns of a written sheet
    routes.py   — routed miles between two addresses, Google Routes API + cache
```

## Before making any changes

1. Read the relevant source file first
2. Check which milestone the change belongs to
3. Do not implement future milestones — one milestone at a time
4. Verify the change doesn't break M1 by checking cli.py imports and scrape flow
5. Do not run the parser over the user's exported data to "demonstrate" a change —
   testing against real data is the user's job
