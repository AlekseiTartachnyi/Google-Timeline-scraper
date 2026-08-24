"""Drive the Timeline list with D-pad focus instead of screen coordinates.

Coordinates taken from the accessibility tree turned out to be unusable for
tapping. uiautomator reports rows that sit outside the scrolled viewport with
ordinary-looking bounds, so the centre of a reported row can land on the map
above the list; the map then pans and the day is lost.

Focus navigation has no coordinates at all. KEYCODE_DPAD_DOWN moves the system
focus to the next focusable node, the framework scrolls that node into view by
itself, and the next dump names the node that KEYCODE_DPAD_CENTER will
activate. That makes the target verifiable *before* it is activated, which a
tap can never be.
"""

import logging
import time

from . import adb
from .extract import UiNode, flatten

logger = logging.getLogger(__name__)

DOWN = "KEYCODE_DPAD_DOWN"
UP = "KEYCODE_DPAD_UP"
CENTER = "KEYCODE_DPAD_CENTER"
ENTER = "KEYCODE_ENTER"
BACK = "KEYCODE_BACK"

# Time for the focus highlight to land and for the list to scroll it into view.
_AFTER_KEY_S = 0.35
# Presses allowed to bring the first highlight up on a screen with no focus yet.
ESTABLISH_PRESSES = 4


def focused_node(serial: str | None = None) -> UiNode | None:
    """Return the node currently holding focus, or None if nothing is focused.

    Several nodes in a dump can carry focused="true" — a window or a container
    reports it alongside the leaf. The leaf is the one that will be activated,
    so a described, focusable node wins over a bare container.
    """
    candidates = [n for n in flatten(adb.dump_ui(serial=serial)) if n.focused]
    if not candidates:
        return None
    described = [n for n in candidates if n.content_desc or n.text]
    return described[-1] if described else candidates[-1]


def label(node: UiNode | None) -> str:
    """Return a short human-readable name for a focused node."""
    if node is None:
        return "<nothing focused>"
    return node.content_desc or node.text or f"<{node.class_name} {node.resource_id}>"


def identity(node: UiNode | None) -> tuple[str, str, str]:
    """Return a value that changes when focus moves to a different node.

    Bounds are deliberately left out: the list scrolls under a focused row, so
    the same row reports different bounds from one dump to the next.
    """
    if node is None:
        return ("", "", "")
    return (node.content_desc, node.text, node.resource_id)


def press(key: str, serial: str | None = None, settle_s: float = _AFTER_KEY_S) -> None:
    """Send one key and give the UI time to react."""
    adb.keyevent(key, serial=serial)
    time.sleep(settle_s)


def establish(serial: str | None = None) -> UiNode | None:
    """Bring up the focus highlight and return the node that has it.

    A screen driven by touch usually has no focused node until the first D-pad
    press, and that first press often only turns the highlight on without
    moving anywhere. Returns None if the screen never takes focus at all.
    """
    node = focused_node(serial=serial)
    if node is not None:
        logger.debug("Focus already on %s", label(node))
        return node
    for attempt in range(1, ESTABLISH_PRESSES + 1):
        press(DOWN, serial=serial)
        node = focused_node(serial=serial)
        if node is not None:
            logger.debug("Focus established after %d press(es): %s", attempt, label(node))
            return node
    return None


def step(key: str = DOWN, serial: str | None = None) -> tuple[UiNode | None, bool]:
    """Move focus one step. Returns (node now focused, whether it moved).

    "Did not move" is how the end of the list announces itself: the last
    focusable node keeps the highlight no matter how often DOWN is pressed.
    """
    before = identity(focused_node(serial=serial))
    press(key, serial=serial)
    after = focused_node(serial=serial)
    return after, identity(after) != before


def walk(serial: str | None = None, max_steps: int = 400, key: str = DOWN):
    """Yield each focused node while stepping through the list.

    Stops when focus stops moving. The first node yielded is the one that
    already holds focus, so a caller can inspect it before stepping on.
    """
    node = establish(serial=serial)
    if node is None:
        return
    yield node
    for _ in range(max_steps):
        node, moved = step(key, serial=serial)
        if not moved or node is None:
            return
        yield node


def focus_row(target: str, serial: str | None = None, max_steps: int = 400) -> bool:
    """Move focus onto the row whose description equals target exactly.

    Exact equality is the point: the row's action buttons (Yes / Edit /
    Add travel) carry the neighbouring row's text inside their own
    description, so anything looser matches a button instead of the row.
    """
    for node in walk(serial=serial, max_steps=max_steps, key=DOWN):
        if node.content_desc == target:
            return True
    return False


def to_start(serial: str | None = None, max_steps: int = 400) -> UiNode | None:
    """Send focus back to the first focusable node and return it.

    Walking up is preferred over swiping the list to the top: a swipe near the
    bottom sheet drags the sheet instead of the list, which enlarges the map
    and moves every row. Focus keys never touch the sheet.
    """
    last: UiNode | None = None
    for node in walk(serial=serial, max_steps=max_steps, key=UP):
        last = node
    return last


def activate(serial: str | None = None, settle_s: float = 0.8) -> None:
    """Activate whatever currently holds focus."""
    press(CENTER, serial=serial, settle_s=settle_s)


def back(serial: str | None = None, settle_s: float = 1.0) -> None:
    """Leave the current screen."""
    press(BACK, serial=serial, settle_s=settle_s)
