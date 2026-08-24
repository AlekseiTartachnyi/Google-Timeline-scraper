"""Two ways to put a finger on a Timeline row, and two gestures to do it with.

Measured on the device: the Timeline day is an `android.webkit.WebView` whose
node covers the entire screen — `[0,0][1080,2410]` on the Pixel. The map and the
list are both inside that one web page. Two consequences drive everything here:

- D-pad focus is not available. A focus walk leaves the WebView immediately and
  stops on a chrome button, so nothing can be selected before it is activated.
- A full-screen WebView is useless as a containment box. Rows are virtual
  accessibility nodes of the web page, and their rectangles are the only
  positional information there is, however unreliable they turn out to be.

So the row has to be found by rectangle, and the rectangle has to be checked
before it is touched. There are two defensible ways to do that check, they fail
differently, and which one survives the phone is an empirical question:

- `locate_strict` — row first. Take the row's rectangle, prove it is stable and
  plausible, tap its centre.
- `locate_anchor` — point first. Fix a point inside the list, scroll until the
  tree says that point is covered by the wanted row, tap the point.
"""

import logging
import time

from . import adb
from .extract import UiNode, flatten

logger = logging.getLogger(__name__)

Rect = tuple[int, int, int, int]
Point = tuple[int, int]

# A row is a single line of text with a time range; anything much taller or
# shorter than this is a container or a stray glyph, not a row.
_MIN_ROW_H = 40
_MAX_ROW_H = 500
# Where in the row to touch. The trailing edge carries action buttons on some
# rows, so stay left of centre.
_ROW_X_FRACTION = 0.30
# The point-first strategy touches here, well below the map and well above the
# navigation bar.
_ANCHOR_Y_FRACTION = 0.62
# One scroll step, as a fraction of screen height. Short, and started away from
# the sheet's top edge so the gesture scrolls the list instead of dragging the
# sheet.
_SCROLL_FROM = 0.72
_SCROLL_TO = 0.52
_SCROLL_SETTLE_S = 0.7
_DUMP_SETTLE_S = 0.4
_MAX_SCROLLS = 14


def parse_rect(bounds: str) -> Rect | None:
    """Return (left, top, right, bottom) from '[l,t][r,b]', or None if degenerate."""
    try:
        left, top, right, bottom = (
            int(c) for c in bounds.replace("][", ",").strip("[]").split(",")
        )
    except ValueError:
        return None
    if right <= left or bottom <= top:
        return None
    return left, top, right, bottom


def row_rects(day_rows: set[str], serial: str | None) -> dict[str, Rect]:
    """Return the rectangle currently reported for each day row on screen."""
    found: dict[str, Rect] = {}
    for node in flatten(adb.dump_ui(serial=serial)):
        if node.content_desc not in day_rows:
            continue
        box = parse_rect(node.bounds)
        if box is not None:
            found.setdefault(node.content_desc, box)
    return found


def _covers(box: Rect, x: int, y: int) -> bool:
    """Return True if the point lies inside the rectangle."""
    left, top, right, bottom = box
    return left <= x <= right and top <= y <= bottom


def _overlaps_vertically(a: Rect, b: Rect) -> bool:
    """Return True if two rows claim the same band of the screen.

    Rows in a list never overlap. When two reported rectangles do, at least one
    of them is describing a position the row does not actually hold.
    """
    return a[1] < b[3] and b[1] < a[3]


def scroll(direction: int, serial: str | None = None) -> None:
    """Scroll the list. direction +1 moves further down the day, -1 back up."""
    width, height = adb.screen_size(serial=serial)
    x = width // 2
    near = int(height * _SCROLL_FROM)
    far = int(height * _SCROLL_TO)
    if direction > 0:
        adb.swipe(x, near, x, far, 400, serial=serial)
    else:
        adb.swipe(x, far, x, near, 400, serial=serial)
    time.sleep(_SCROLL_SETTLE_S)


# ---------------------------------------------------------------------------
# gestures
# ---------------------------------------------------------------------------

def tap_instant(point: Point, serial: str | None = None) -> None:
    """Touch down and up with no measurable delay — `input tap`."""
    adb.tap(point[0], point[1], serial=serial)


def tap_gesture(point: Point, serial: str | None = None) -> None:
    """Touch down, hold briefly, lift — a swipe of zero length.

    Web content sometimes ignores an instantaneous tap because the page never
    sees a settled touch. A held touch is what a finger actually produces.
    """
    adb.swipe(point[0], point[1], point[0], point[1], 120, serial=serial)


# ---------------------------------------------------------------------------
# strategy 1 — row first
# ---------------------------------------------------------------------------

def locate_strict(target: str, day_rows: set[str], serial: str | None = None) -> Point | None:
    """Return where to touch the row, or None if its rectangle cannot be trusted.

    The rectangle has to survive three checks: it must be identical in two
    consecutive dumps (so the list is not still moving), it must be a plausible
    row height fully inside the screen, and it must not share a band of the
    screen with another row (rows in a list do not overlap; when the tree says
    they do, the coordinates are describing something other than the layout).
    """
    width, height = adb.screen_size(serial=serial)

    for attempt in range(1, _MAX_SCROLLS + 1):
        first = row_rects(day_rows, serial)
        time.sleep(_DUMP_SETTLE_S)
        second = row_rects(day_rows, serial)

        box = second.get(target)
        if box is None:
            logger.debug("strict: row not in the tree (attempt %d)", attempt)
            scroll(+1, serial=serial)
            continue

        if first.get(target) != box:
            logger.debug("strict: rectangle changed between dumps, list still moving")
            time.sleep(_SCROLL_SETTLE_S)
            continue

        left, top, right, bottom = box
        if not (0 <= left and 0 <= top and right <= width and bottom <= height):
            logger.info("strict: %r is off screen at %s — scrolling", target, box)
            scroll(+1 if top >= height else -1, serial=serial)
            continue

        row_height = bottom - top
        if not (_MIN_ROW_H <= row_height <= _MAX_ROW_H):
            logger.warning("strict: %r has an implausible height of %d px", target, row_height)
            return None

        clash = [
            other
            for desc, other in second.items()
            if desc != target and _overlaps_vertically(box, other)
        ]
        if clash:
            logger.warning(
                "strict: %r at %s overlaps %d other row(s) — the tree is not "
                "describing the visible layout",
                target,
                box,
                len(clash),
            )
            scroll(+1, serial=serial)
            continue

        x = int(left + (right - left) * _ROW_X_FRACTION)
        y = (top + bottom) // 2
        logger.info("strict: %r accepted at %s, touching (%d, %d)", target, box, x, y)
        return x, y

    logger.warning("strict: gave up on %r after %d attempts", target, _MAX_SCROLLS)
    return None


# ---------------------------------------------------------------------------
# strategy 2 — point first
# ---------------------------------------------------------------------------

def locate_anchor(target: str, day_rows: set[str], serial: str | None = None) -> Point | None:
    """Return a fixed point inside the list once the wanted row covers it.

    The question is inverted: instead of asking where the row is and trusting
    the answer, this asks what is under one chosen point and scrolls until the
    answer is the row we want. A rectangle that is wrong about its position
    cannot pull the touch away from the list, because the touch point never
    moves.
    """
    width, height = adb.screen_size(serial=serial)
    x = width // 2
    y = int(height * _ANCHOR_Y_FRACTION)

    for attempt in range(1, _MAX_SCROLLS + 1):
        rows = row_rects(day_rows, serial)
        under = [desc for desc, box in rows.items() if _covers(box, x, y)]
        if target in under:
            logger.info(
                "anchor: %r covers the anchor (%d, %d) after %d scroll(s)",
                target,
                x,
                y,
                attempt - 1,
            )
            return x, y

        box = rows.get(target)
        if box is None:
            logger.debug("anchor: %r not in the tree yet, scrolling down", target)
            scroll(+1, serial=serial)
            continue

        centre = (box[1] + box[3]) // 2
        direction = +1 if centre > y else -1
        logger.debug(
            "anchor: %r centred at y=%d, anchor at y=%d, scrolling %s",
            target,
            centre,
            y,
            "down" if direction > 0 else "up",
        )
        scroll(direction, serial=serial)

    logger.warning("anchor: %r never reached the anchor point", target)
    return None


def describe_node_at(point: Point, serial: str | None = None) -> str:
    """Return the smallest described node covering a point — what a touch hits."""
    hits: list[UiNode] = []
    for node in flatten(adb.dump_ui(serial=serial)):
        box = parse_rect(node.bounds)
        if box is not None and _covers(box, *point) and (node.content_desc or node.text):
            hits.append(node)
    if not hits:
        return "<nothing described covers that point>"
    smallest = min(hits, key=lambda n: _area(parse_rect(n.bounds)))
    return f"{smallest.class_name} desc={smallest.content_desc!r} text={smallest.text!r}"


def _area(box: Rect | None) -> int:
    """Return the area of a rectangle, or a huge number for None."""
    if box is None:
        return 1 << 30
    return (box[2] - box[0]) * (box[3] - box[1])
