# M2.2 — the trip screenshot pass

## What the day screen is

Measured with a focus walk on the device:

```
[  0] desc='' text='' class=android.webkit.WebView id= bounds=[0,0][1080,2410]
[  1] desc='Backup enabled.' text='' class=android.widget.Button bounds=[672,202][798,330]
focus stopped moving after 1 step
```

The Timeline day is one full-screen WebView holding both the map and the list. That kills
two approaches outright:

- **Focus navigation is dead.** The walk leaves the WebView on its first step and stops on
  a chrome button. No row can be selected before it is activated.
- **Containment checks against the container are dead.** The container is the screen, so
  "is this rectangle inside the list" has no meaning. Rows are virtual accessibility nodes
  of the web page, and their rectangles are all the positional information that exists.

## The defect

`capture.py` takes the rectangle a row reports and touches its centre. On the phone the
touch lands on the map, the map pans, and the screenshot is of the day view.

The rectangle is therefore wrong, stale, or describing something other than the visible
layout — and which of those it is decides the fix. That is a measurement, not an argument,
so both defensible strategies are implemented and run side by side.

## The two strategies

Both live in `tap.py` and share a signature: given a row's description, return the point to
touch, or None if the row cannot be reached honestly.

**`locate_strict` — row first.** Take the row's rectangle and refuse to touch it unless it
passes three checks:

1. identical in two consecutive dumps, so the list is not still moving;
2. a plausible row height, fully inside the screen;
3. not sharing a band of the screen with another row — rows in a list never overlap, so an
   overlap proves the tree is not describing the visible layout.

Touched with `input tap`, at 30% of the row's width so the trailing action buttons are
clear of the finger.

**`locate_anchor` — point first.** Fix one point at 62% of screen height, well below the
map. Scroll until the tree says *that point* is covered by the wanted row, then touch the
point. A rectangle that lies about its position cannot drag the finger onto the map,
because the finger never moves.

Touched with a held gesture (`input swipe x y x y 120`) rather than `input tap`, because
web content sometimes ignores an instantaneous touch it never sees settle.

The two differ in both targeting and gesture on purpose: between them they cover stale
rectangles, off-viewport rectangles, and a page that ignores instant taps.

## Running the experiment

```
py -m timeline_scraper scrape --tap-lab
```

Each variant gets the same first two driving trips of the day. The day is reopened between
variants so neither inherits the other's scroll position or a map the previous run panned.

Output, per variant and run:

```
exports/draft-screenshots/<variant>/<YYYY-Mon-DD-HHMM>/
    01-<time>-1-before.xml / .png      the tree and the screen before the touch
    01-<time>-2-target.txt             the point chosen, and what the tree says is under it
    01-<time>-3-after-tap.xml / .png   the screen straight after the touch
    <hhmm>-<hhmm>_driving.png          the settled map, only if the trip opened
    result.txt                         one line per trip
```

`result.txt` distinguishes the four outcomes that matter:

| line | meaning |
| --- | --- |
| `OPENED` | the strategy works — the map is in the folder |
| `NOT LOCATED` | the rectangle never passed the checks; nothing was touched |
| `NO REACTION` | the touch landed and the screen did not change by a single byte |
| `WRONG TARGET` | the screen changed but the trip did not open — the map moved |

`NO REACTION` and `WRONG TARGET` both name what the tree says was under the touch point,
which is the line that identifies whether the coordinate or the gesture is at fault.

## Untouched, still working

- `extract.collect_day` — scrolls the day and returns every description in order.
- `parse.build_day` — descriptions to `Visit` / `Trip`, endpoints linked by exact clock match.
- `model.write_day_json` — the day's JSON, written before the screenshot pass and again
  after, so a broken capture never costs the day's data.

## Confirmed behaviour to design around

- The map zooms to fit the trip. A long trip barely changes the view; a short trip zooms in
  and loads new tiles, so it needs more settling time. `wait_for_map` polls screenshots
  until two in a row are identical instead of sleeping a fixed amount.
- Rows must be located again on every pass. Remembered positions are always wrong.
- `trip.raw_text` equals the row's `content-desc` exactly.
- Swipes start at 72% of screen height, not 80%: near the bottom sheet's edge the gesture
  drags the sheet instead of scrolling the list, which enlarges the map and moves every row.

## Files

- `src/timeline_scraper/tap.py` — `locate_strict`, `locate_anchor`, `tap_instant`,
  `tap_gesture`, `describe_node_at`.
- `src/timeline_scraper/taplab.py` — `run_tap_lab`, the side-by-side run.
- `src/timeline_scraper/capture.py` — the normal pass; takes the strategy as a parameter.
- `src/timeline_scraper/cli.py` — `--tap-lab`, `--no-screenshots`.
