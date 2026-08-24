# M2.2 — trip screenshots by focus navigation

## The defect this replaces

`capture.py` used to locate a `Driving` row in the accessibility tree and tap the centre of
its `bounds`. The tap landed on the map above the list, the map panned, and the screenshot
was of the day view.

The root cause is that `bounds` are not proof of visibility. uiautomator reports rows sitting
outside the scrolled viewport with ordinary-looking coordinates, and the old
`_tap_target` rejected only `[0,0][0,0]`. A row just past the edge of the list yields a
coordinate that falls on the map. Related: swiping the list from 35% to 80% of the screen
drags the bottom sheet instead of the list, which enlarges the map and moves every row.

Both problems are properties of coordinates. So coordinates are gone from this pass.

## What it does now

`focus.py` drives the list with `KEYCODE_DPAD_DOWN` / `KEYCODE_DPAD_CENTER`:

- No coordinate is computed, so no tap can land on the map.
- The framework scrolls the focused row into view itself, so "off-screen row" cannot happen.
- The dump reports `focused="true"` on the row *before* it is activated, so the row about to
  open is known by name and checked against `trip.raw_text`.
- Returning to the top of the list is `KEYCODE_DPAD_UP` until focus stops moving — no swipe,
  so the bottom sheet is never dragged.

Matching stays exact equality with `trip.raw_text`. The action buttons (`Yes`, `Edit`,
`Add travel`) carry the neighbouring row's text inside a description that *starts* with the
button name, so exact equality never selects one.

`capture_trip_maps` sweeps the list top to bottom. On a pending row it activates, waits for
the map to stop changing, saves the PNG, presses Back, and checks whether focus survived. If
it did, the sweep continues from that row; if it did not, a fresh sweep starts from the top.
Rows already captured are skipped, so restarts are cheap and cannot loop.

## The unknowns, and how to measure them

Three things were guessed at before and must be read off the device instead:

- what the trip screen's tree actually contains (there is no confirmed Back or header node —
  `_opened` still infers "opened" from the day's other rows leaving the screen);
- whether the list takes D-pad focus at all, and in what order;
- where focus and the sheet end up after Back.

```
py -m timeline_scraper scrape --probe-focus
```

Navigates to the day, then writes a timestamped `probe-*` directory under the export folder:

| file | what it answers |
| --- | --- |
| `01-day.xml` / `.png` / `-nodes.txt` | the day list as the tree sees it |
| `focus-walk.txt` | every stop of the focus walk, in order, or a note that focus is unavailable |
| `02-row-focused.xml` / `.png` | the first `Driving` row with the highlight on it |
| `03-after-activate.xml` / `.png` / `-nodes.txt` | what activation actually opened |
| `04-after-back.xml` / `.png` | where Back leaves the screen, and where focus lands |

If `focus-walk.txt` says focus could not be established, variant A is dead on this build of
Maps and the fallback is a containment-checked tap: find the `scrollable` container in the
same dump and tap only rows whose rectangle lies fully inside it.

## Untouched, still working

- `extract.collect_day` — scrolls the day and returns every description in order.
- `parse.build_day` — descriptions to `Visit` / `Trip`, endpoints linked by exact clock match.
- `model.write_day_json` — `~/timeline-exports/timeline_<YYYYMMDD>.draft.json`.

The JSON is written before the screenshot pass and rewritten after, so a broken capture never
costs the day's data.

## Confirmed behaviour to design around

- The map zooms to fit the trip. A long trip barely changes the view; a short trip zooms in and
  loads new tiles, so it needs more settling time, not less. `_wait_for_map` polls screenshots
  until two in a row are identical rather than sleeping a fixed amount.
- Rows must be located again on every pass. Remembered positions are always wrong.
- `trip.raw_text` equals the row's `content-desc` exactly.

## Files

- `src/timeline_scraper/focus.py` — D-pad primitives: `focused_node`, `step`, `walk`,
  `to_start`, `focus_row`, `activate`, `back`.
- `src/timeline_scraper/capture.py` — the sweep: `capture_trip_maps`, `_open_focused`, `_opened`.
- `src/timeline_scraper/probe.py` — `probe_focus`, the measurement run.
- `src/timeline_scraper/cli.py` — `--probe-focus`, `--no-screenshots`.
