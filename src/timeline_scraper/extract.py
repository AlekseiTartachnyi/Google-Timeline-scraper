"""Flatten a uiautomator UI dump into ordered, inspectable element records."""

import logging
import time
from dataclasses import dataclass
from xml.etree import ElementTree as ET

from .adb import dump_ui, swipe

logger = logging.getLogger(__name__)

_SCROLL_WAIT_S = 1.0


@dataclass
class UiNode:
    """A single on-screen element, as reported by the accessibility tree."""

    index: int
    text: str
    content_desc: str
    resource_id: str
    class_name: str
    clickable: bool
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
        if not text and not content_desc and not clickable:
            continue
        nodes.append(
            UiNode(
                index=i,
                text=text,
                content_desc=content_desc,
                resource_id=node.get("resource-id", ""),
                class_name=node.get("class", ""),
                clickable=clickable,
                bounds=node.get("bounds", ""),
            )
        )
    return nodes


def log_nodes(nodes: list[UiNode]) -> None:
    """Log every node so the on-screen layout can be inspected from the console."""
    logger.info("Visible elements (%d):", len(nodes))
    for n in nodes:
        logger.info(
            "  [%3d] text=%r desc=%r id=%r class=%r clickable=%s bounds=%s",
            n.index,
            n.text,
            n.content_desc,
            n.resource_id,
            n.class_name,
            n.clickable,
            n.bounds,
        )


def _bounds_box(bounds: str) -> tuple[int, int, int, int] | None:
    """Parse a bounds string '[l,t][r,b]' into (left, top, right, bottom).

    Returns None if bounds is empty or malformed.
    """
    if not bounds:
        return None
    try:
        left, top, right, bottom = (
            int(c) for c in bounds.replace("][", ",").strip("[]").split(",")
        )
        return left, top, right, bottom
    except ValueError:
        return None


def group_rows(nodes: list[UiNode]) -> list[list[UiNode]]:
    """Cluster a flat, ordered node list into rows, using content_desc as
    the row-start signal.

    Bounds can't be used for this: on a real dump, most Timeline entries
    report bounds "[0,0][0,0]" once they're off the physical screen
    (virtualized/recycled by the list), even though their text/content_desc
    is still present in the tree. What real dumps show instead is that each
    entry — a visit, a trip segment, a "Missing travel" gap, a "Yes"/"Edit"
    action — carries its full description as one Button's content_desc. So
    a new row starts at every node with a non-empty content_desc; anything
    else (icon-only companion buttons with no label, or a plain-text
    sub-block like a "Places: Target, Department store" guess) attaches to
    whatever row is currently open, so it's kept without becoming a row
    boundary itself.
    """
    rows: list[list[UiNode]] = []
    current: list[UiNode] = []

    for node in nodes:
        if node.content_desc and current:
            rows.append(current)
            current = []
        current.append(node)

    if current:
        rows.append(current)
    return rows


def _row_signature(row: list[UiNode]) -> tuple[tuple[str, str], ...]:
    """Return a content-based identity for a row, ignoring position/bounds.

    Used to recognize the same entry reappearing after a scroll, since its
    bounds shift but its text/content-desc do not.
    """
    return tuple((n.text, n.content_desc) for n in row)


def capture_day_rows(serial: str | None = None, max_scrolls: int = 200) -> list[list[UiNode]]:
    """Scroll the current Timeline day screen top to bottom, collecting every row.

    Repeatedly dumps the UI and groups nodes into rows (see `group_rows`),
    appending rows not already seen — by content signature — to an
    accumulated, ordered list. Stops once a scroll adds no new rows, or
    after `max_scrolls` swipes as a safety cap against a runaway loop.
    """
    seen: set[tuple[tuple[str, str], ...]] = set()
    all_rows: list[list[UiNode]] = []
    scroll_count = 0

    while True:
        root = dump_ui(serial=serial)
        rows = group_rows(flatten(root))
        new_rows = [r for r in rows if _row_signature(r) not in seen]
        for row in new_rows:
            seen.add(_row_signature(row))
            all_rows.append(row)

        logger.info(
            "Dump %d: %d rows on screen, %d new (%d total)",
            scroll_count, len(rows), len(new_rows), len(all_rows),
        )

        if scroll_count > 0 and not new_rows:
            logger.info("No new rows after scrolling — reached the end of the day")
            break
        if scroll_count >= max_scrolls:
            logger.warning("Hit max_scrolls (%d) without confirming the end of the day", max_scrolls)
            break

        first_node = next(root.iter("node"), None)
        box = _bounds_box(first_node.get("bounds", "")) if first_node is not None else None
        if box is None:
            logger.warning("Could not read screen bounds for swipe; stopping")
            break
        left, top, right, bottom = box
        x = (left + right) // 2
        y_start = top + int(0.8 * (bottom - top))
        y_end = top + int(0.2 * (bottom - top))
        swipe(x, y_start, x, y_end, serial=serial)
        time.sleep(_SCROLL_WAIT_S)
        scroll_count += 1

    return all_rows
