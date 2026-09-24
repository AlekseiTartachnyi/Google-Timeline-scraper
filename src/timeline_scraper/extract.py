"""Flatten a uiautomator UI dump into ordered, inspectable element records."""

import logging
import time
from dataclasses import dataclass
from xml.etree import ElementTree as ET

from . import adb

logger = logging.getLogger(__name__)

# Time for the list to stop moving after a swipe.
_SCROLL_SETTLE_S = 0.6

# Where the day list actually is on the screen.
#
# Measured 2026-Sep-24 from two screenshots of the same day taken at different
# scroll positions: every pixel above 0.585 of the screen height was identical
# in both. The status bar, the Timeline header, the Day/Trips/Insights tab
# strip, the whole map, and the day bar `< Sun, Aug 30, 2026 >` do not move
# when the day is scrolled. Only the strip below them does, and on this Pixel
# that strip is 1002 px of a 2410 px screen — 42% of it, not all of it.
_LIST_TOP = 0.585
_LIST_BOTTOM = 0.99
# Keep the touch off the very bottom edge, where Android's own back and home
# gestures live.
_EDGE = 0.06

# How much of that strip one swipe travels. Deliberately less than all of it:
# what is left over is the overlap between one screenful and the next, and the
# overlap is the only thing keeping a row from falling down the seam between
# two screens.
#
# The swipe this replaced ran from 0.80 to 0.35 of the screen: 1084 px against
# a strip 1002 px tall, so every swipe moved the list more than a full
# screenful — and ended 565 px above the list, inside the map. That is what
# lost rows between screens.
_STEP = 0.70


@dataclass
class UiNode:
    """A single on-screen element, as reported by the accessibility tree."""

    index: int
    text: str
    content_desc: str
    resource_id: str
    class_name: str
    clickable: bool
    focusable: bool
    focused: bool
    selected: bool
    bounds: str


def flatten(root: ET.Element) -> list[UiNode]:
    """Return every node worth looking at, in document order.

    Keeps a node if it carries visible text, an accessibility description,
    or is clickable (so icon-only buttons with no text are still captured).
    Empty layout containers that carry none of that are dropped as noise.
    """
    nodes: list[UiNode] = []
    for i, node in enumerate(root.iter("node")):
        text = node.get("text", "")
        content_desc = node.get("content-desc", "")
        clickable = node.get("clickable") == "true"
        focused = node.get("focused") == "true"
        if not text and not content_desc and not clickable and not focused:
            continue
        nodes.append(
            UiNode(
                index=i,
                text=text,
                content_desc=content_desc,
                resource_id=node.get("resource-id", ""),
                class_name=node.get("class", ""),
                clickable=clickable,
                focusable=node.get("focusable") == "true",
                focused=focused,
                selected=node.get("selected") == "true",
                bounds=node.get("bounds", ""),
            )
        )
    return nodes


def log_nodes(nodes: list[UiNode]) -> None:
    """Log every node so the on-screen layout can be inspected from the console."""
    logger.info("Visible elements (%d):", len(nodes))
    for n in nodes:
        logger.info(
            "  [%3d] text=%r desc=%r id=%r class=%r clickable=%s focusable=%s "
            "focused=%s selected=%s bounds=%s",
            n.index,
            n.text,
            n.content_desc,
            n.resource_id,
            n.class_name,
            n.clickable,
            n.focusable,
            n.focused,
            n.selected,
            n.bounds,
        )


def descriptions(nodes: list[UiNode]) -> list[str]:
    """Return the accessibility descriptions of nodes that carry one, in order."""
    return [n.content_desc for n in nodes if n.content_desc]


def list_band(serial: str | None = None) -> tuple[int, int, int]:
    """Return (x, top, bottom) of the strip the day list scrolls in, in pixels.

    Both ends of every scrolling gesture have to land inside this strip. A
    touch that starts or finishes above it is on the map, which is a different
    thing that also responds to being dragged.
    """
    width, height = adb.screen_size(serial=serial)
    top = int(height * _LIST_TOP)
    bottom = int(height * (_LIST_BOTTOM - _EDGE))
    return width // 2, top, bottom


def scroll_step(serial: str | None = None) -> None:
    """Advance the day list by most of one screenful, and wait for it to settle.

    One gesture, defined once, so anything that walks a day — collecting its
    rows, photographing it — moves the list the same way rather than inventing
    a gesture of its own. It stays inside the list strip and stops short of a
    full screenful, so consecutive screens overlap instead of meeting at a seam
    a row can fall through.
    """
    x, top, bottom = list_band(serial=serial)
    travel = int((bottom - top) * _STEP)
    adb.swipe(x, bottom, x, bottom - travel, 400, serial=serial)
    time.sleep(_SCROLL_SETTLE_S)


def collect_day(serial: str | None = None, max_swipes: int = 40) -> list[str]:
    """Scroll the whole day and return every accessibility description, in order.

    Swipes up until a full pass adds nothing new, merging each dump into the
    running list. Duplicates are dropped, order of first appearance is kept.
    """
    collected: list[str] = []
    seen: set[str] = set()

    for swipe_index in range(max_swipes):
        added = 0
        for desc in descriptions(flatten(adb.dump_ui(serial=serial))):
            if desc not in seen:
                seen.add(desc)
                collected.append(desc)
                added += 1
        logger.debug("Scroll pass %d: %d new rows (%d total)", swipe_index, added, len(collected))
        if added == 0:
            break
        scroll_step(serial=serial)

    logger.info("Collected %d rows from the Timeline list", len(collected))
    return collected


def scroll_to_top(serial: str | None = None, max_swipes: int = 40) -> None:
    """Swipe the day list back to its first row.

    Collecting a day leaves the list at the bottom, and a day has to be back at
    its first row before the app bar above it can be used.

    What says the top has been reached is the whole list of descriptions, not
    the first few of them. The first few are the header and the tab strip: they
    are the same at the top of a day and at the bottom, so a walk that judged
    by them stopped after a single swipe and left a long day halfway up.
    """
    x, top, bottom = list_band(serial=serial)
    previous: list[str] | None = None

    for swipe_index in range(max_swipes):
        current = descriptions(flatten(adb.dump_ui(serial=serial)))
        if current and current == previous:
            logger.debug("Day list is back at the top after %d swipe(s)", swipe_index)
            return
        previous = current
        travel = int((bottom - top) * _STEP)
        adb.swipe(x, bottom - travel, x, bottom, 400, serial=serial)
        time.sleep(_SCROLL_SETTLE_S)

    logger.warning("Day list still moving after %d swipes down", max_swipes)


def parse_bounds(bounds: str) -> tuple[int, int, int, int] | None:
    """Return (left, top, right, bottom) of a bounds string '[l,t][r,b]', or None.

    Rows merged from an earlier scroll report '[0,0][0,0]'; those are not on
    screen and carry no rectangle worth having.
    """
    try:
        left, top, right, bottom = (
            int(c) for c in bounds.replace("][", ",").strip("[]").split(",")
        )
    except ValueError:
        return None
    if right <= left or bottom <= top:
        return None
    return left, top, right, bottom


def parse_bounds_center(bounds: str) -> tuple[int, int] | None:
    """Return the center pixel of a bounds string '[l,t][r,b]', or None.

    Rows merged from an earlier scroll report '[0,0][0,0]'; those are not on
    screen and must not be tapped.
    """
    rect = parse_bounds(bounds)
    if rect is None:
        return None
    left, top, right, bottom = rect
    return (left + right) // 2, (top + bottom) // 2


def list_rows(nodes: list[UiNode], top: int) -> list[str]:
    """Return the descriptions of the nodes that sit in the scrolling strip.

    The header, the tab strip, the map and the day bar carry descriptions too,
    and they are the same at the top of a day and at the bottom. Anything that
    has to tell one screenful from the next has to ignore them, and where they
    end is the one thing about this screen that has been measured.
    """
    rows: list[str] = []
    for node in nodes:
        if not node.content_desc:
            continue
        rect = parse_bounds(node.bounds)
        if rect is not None and rect[1] >= top:
            rows.append(node.content_desc)
    return rows
