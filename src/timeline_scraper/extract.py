"""Flatten a uiautomator UI dump into ordered, inspectable element records."""

import logging
import time
from dataclasses import dataclass
from xml.etree import ElementTree as ET

from . import adb

logger = logging.getLogger(__name__)

# Time for the list to stop moving after a swipe.
_SCROLL_SETTLE_S = 0.6


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


def collect_day(serial: str | None = None, max_swipes: int = 40) -> list[str]:
    """Scroll the whole day and return every accessibility description, in order.

    Swipes up until a full pass adds nothing new, merging each dump into the
    running list. Duplicates are dropped, order of first appearance is kept.
    """
    width, height = adb.screen_size(serial=serial)
    x = width // 2
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
        adb.swipe(x, int(height * 0.80), x, int(height * 0.35), 400, serial=serial)
        time.sleep(_SCROLL_SETTLE_S)

    logger.info("Collected %d rows from the Timeline list", len(collected))
    return collected


def scroll_to_top(serial: str | None = None, max_swipes: int = 40) -> None:
    """Swipe the day list back to its first row.

    Collecting a day leaves the list at the bottom. The date header and the
    calendar chip scroll with the page — they are rows of the same web view,
    not Android chrome — so the way back to the calendar starts with putting
    the top of the list back on screen.
    """
    width, height = adb.screen_size(serial=serial)
    x = width // 2
    previous: list[str] | None = None

    for swipe_index in range(max_swipes):
        current = descriptions(flatten(adb.dump_ui(serial=serial)))[:3]
        if current and current == previous:
            logger.debug("Day list is back at the top after %d swipe(s)", swipe_index)
            return
        previous = current
        adb.swipe(x, int(height * 0.35), x, int(height * 0.80), 400, serial=serial)
        time.sleep(_SCROLL_SETTLE_S)

    logger.warning("Day list still moving after %d swipes down", max_swipes)


def parse_bounds_center(bounds: str) -> tuple[int, int] | None:
    """Return the center pixel of a bounds string '[l,t][r,b]', or None.

    Rows merged from an earlier scroll report '[0,0][0,0]'; those are not on
    screen and must not be tapped.
    """
    try:
        left, top, right, bottom = (
            int(c) for c in bounds.replace("][", ",").strip("[]").split(",")
        )
    except ValueError:
        return None
    if right <= left or bottom <= top:
        return None
    return (left + right) // 2, (top + bottom) // 2
