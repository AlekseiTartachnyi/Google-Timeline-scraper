# M2.2 handoff — trip screenshots tap the wrong place

## State

Working, do not touch:

- `extract.collect_day` — scrolls the day and returns every accessibility description in order.
- `parse.build_day` — descriptions to `Visit` / `Trip`, endpoints linked by exact clock match.
- `model.write_day_json` — `~/timeline-exports/timeline_<YYYYMMDD>.draft.json`.

Broken:

- `capture.py` — the screenshot pass. The tap lands on the map instead of the `Driving` row,
  so the trip screen never opens and the screenshot is of the day view.

## Symptom

`capture_trip_maps` walks the day list, finds the row whose `content-desc` equals
`trip.raw_text`, taps the centre of its `bounds`, and expects the trip screen. Observed on
the phone: the tap hits the map area above the list.

## Why it can happen — check these in this order

1. **`bounds` are not proof of visibility.** `uiautomator` reports rows that sit outside the
   scrolled viewport with ordinary-looking coordinates. `capture._tap_target` only rejects
   `[0,0][0,0]`. A row just outside the list can carry coordinates that fall on the map.
   Fix: find the scrollable list container in the same dump, and tap only when the row's
   rectangle is fully inside it.
2. **`extract.scroll_to_top` may be closing the sheet, not scrolling the list.** It swipes
   down from 35% to 80% of the screen. On a bottom sheet that gesture can drag the sheet
   itself down, which enlarges the map and moves every row. Fix: scroll inside the list
   container's own rectangle, and re-read the tree after each swipe.
3. **Duplicate `content-desc`.** The same description appears on the row Button and on its
   action buttons (`Yes`, `Edit`, `Add travel` carry the neighbouring row's text). Fix: match
   on the row itself — the clickable node whose description *starts* with the movement head,
   not a node whose description merely contains the row text.
4. **Dump taken while the list is still moving.** After a swipe the coordinates go stale
   within one frame. Fix: dump twice and only act when two consecutive dumps agree.

## Must be measured on the device before writing more code

These are unknown and must not be guessed:

- What the trip screen's accessibility tree actually contains — there is no confirmed Back or
  header node. `capture._opened` currently infers "opened" from the day's other rows leaving
  the screen; confirm or replace that with something real from a dump.
- How many taps a row actually needs, and what the first tap does when it is not the trip
  screen (expands the sheet? scrolls? nothing?).
- Where the sheet and the list end up after `KEYCODE_BACK`.

Recommended probe: on the day view, dump the tree, tap one `Driving` row, dump again, press
Back, dump again. Three dumps answer all of the above.

## Confirmed behaviour to design around

- The map zooms to fit the trip. A long trip barely changes the view; a short trip zooms in and
  has to load new tiles, so it needs more settling time, not less.
- Rows must be located again on every pass. Scrolling and Back both move them, so remembered
  coordinates are always wrong.
- `trip.raw_text` is the tap target and matches the row's `content-desc` exactly.

## Files

- `src/timeline_scraper/capture.py` — `_tap_target`, `_opened`, `capture_trip_maps`.
- `src/timeline_scraper/extract.py` — `scroll_to_top`, `parse_bounds_center`.
- `src/timeline_scraper/cli.py` — calls `capture_trip_maps` after the JSON is written;
  `--no-screenshots` skips it.

The JSON is written before the screenshot pass and rewritten after, so a broken capture never
costs the day's data.
