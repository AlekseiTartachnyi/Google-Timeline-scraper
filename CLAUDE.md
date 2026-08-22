# CLAUDE.md — Project instructions for AI assistants

## What this project is

ADB-driven scraper that reads Google Maps Timeline from a Pixel phone (English UI)
and exports everything visible on screen to JSON, then to CSV for mileage labeling.

Spec: `timeline-scraper-spec.md`

## How to run

```
py -m timeline_scraper scrape
```

On Windows use `py`, not `python`. The `python` command is intercepted by a Windows
App Execution Alias and redirects to the Microsoft Store.

## Execution environment — read this once, do not re-derive or re-explain it

Sessions for this project run in two different places:

- **Local (user's laptop/Mac Mini)** — a real Pixel is plugged in over USB, `adb` is
  installed, `adb devices` shows the phone. `scrape` actually drives the phone here.
- **Cloud (Claude Code on the web)** — an isolated container. No USB, no phone, `adb`
  isn't even installed. `scrape` cannot execute here.

If `adb`/a device is missing in the current session, that's just which of the two this
session is — not a bug in `adb.py`/`nav.py`, not something to fix, and not something to
explain to the user again. They already know; they run the device side themselves. When
real UI-tree structure or output is needed to design or verify extraction logic, ask once
for the console log or JSON/XML the user captured by running `scrape` locally, then move on.

## Current milestone status

- [x] M1 — ADB preflight, wake screen, launch Maps, navigate to Timeline
- [ ] M2 — Capture one day to JSON
- [ ] M3 — Scrape 7 days with crash-safe incremental save
- [ ] M4 — Flatten to CSV
- [ ] M5 — Full month export
- [ ] M6 — Polish: interactive prompts, logging, tests

## Working branch

Whatever branch the current session/task was assigned — check the task instructions, not
this file. `main` is the up-to-date integration branch after merges.

If local files seem wrong (errors from code you didn't write), diff against `origin/main`
rather than resetting to a specific milestone branch name — an old milestone branch (e.g.
M1's) is behind `main` once later work has merged, and resetting to it discards that work.

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
    model.py    — (M2) data model + JSON serialization
    extract.py  — (M2) UI dump -> ordered text blocks, scroll + dedupe
    parse.py    — (M4) best-effort structured fields
    flatten.py  — (M4) JSON -> CSV
tests/
    fixtures/   — anonymized uiautomator XML dumps (no real location data)
```

## Before making any changes

1. Read the relevant source file first
2. Check which milestone the change belongs to
3. Do not implement future milestones — one milestone at a time
4. Verify the change doesn't break M1 by checking cli.py imports and scrape flow
