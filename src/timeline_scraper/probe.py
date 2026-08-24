"""Measure how the Timeline screen behaves under D-pad focus.

Nothing here is part of a normal scrape. It exists because the trip screen's
accessibility tree, the focus order of the day list, and where Back leaves the
list were all guessed at before — and the guesses were wrong. This writes the
dumps to disk so they can be read instead of guessed.

Run it with:  py -m timeline_scraper scrape --probe-focus
"""

import logging
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree as ET

from . import adb, focus
from .extract import flatten

logger = logging.getLogger(__name__)

_MAX_WALK_STEPS = 80


def _save_dump(out_dir: Path, name: str, serial: str | None) -> ET.Element:
    """Dump the tree, write it as XML next to a screenshot, and return the root."""
    root = adb.dump_ui(serial=serial)
    (out_dir / f"{name}.xml").write_bytes(ET.tostring(root, encoding="utf-8"))
    (out_dir / f"{name}.png").write_bytes(adb.screencap(serial=serial))
    logger.info("Saved %s.xml and %s.png", name, name)
    return root


def _describe(root: ET.Element) -> list[str]:
    """Return one readable line per node in the tree."""
    return [
        f"desc={n.content_desc!r} text={n.text!r} class={n.class_name} "
        f"id={n.resource_id} clickable={n.clickable} focusable={n.focusable} "
        f"focused={n.focused} selected={n.selected} bounds={n.bounds}"
        for n in flatten(root)
    ]


def _walk_focus(out_dir: Path, serial: str | None) -> list[str]:
    """Step focus through the list, log every stop, and return the stops."""
    lines: list[str] = []
    stops: list[str] = []
    node = focus.establish(serial=serial)
    if node is None:
        logger.error(
            "No node reports focused=true after %d presses of %s — this screen "
            "does not take D-pad focus.",
            focus.ESTABLISH_PRESSES,
            focus.DOWN,
        )
        (out_dir / "focus-walk.txt").write_text(
            "focus could not be established\n", encoding="utf-8"
        )
        return stops

    step_index = 0
    while True:
        line = (
            f"[{step_index:3d}] desc={node.content_desc!r} text={node.text!r} "
            f"class={node.class_name} id={node.resource_id} bounds={node.bounds}"
        )
        logger.info("  %s", line)
        lines.append(line)
        stops.append(node.content_desc)
        if step_index >= _MAX_WALK_STEPS:
            lines.append("stopped: step limit reached")
            break
        node, moved = focus.step(focus.DOWN, serial=serial)
        if not moved or node is None:
            lines.append("stopped: focus no longer moves (end of list)")
            logger.info("  focus stopped moving after %d step(s)", step_index)
            break
        step_index += 1

    (out_dir / "focus-walk.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return stops


def probe_focus(out_dir: Path, serial: str | None = None, mode: str = "Driving") -> Path:
    """Record how focus moves on the day list and what opening a row produces.

    Writes to a timestamped directory: the day screen, the whole focus walk,
    the row about to be opened, the screen it opens, and the screen Back
    leaves behind. Returns the directory.
    """
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = out_dir / f"probe-{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Focus probe -> %s", out_dir)

    day = _save_dump(out_dir, "01-day", serial)
    (out_dir / "01-day-nodes.txt").write_text(
        "\n".join(_describe(day)) + "\n", encoding="utf-8"
    )

    logger.info("Walking focus down the day list:")
    stops = _walk_focus(out_dir, serial)
    if not stops:
        logger.error("Focus navigation is unavailable on this screen — stopping the probe.")
        return out_dir

    row = next((s for s in stops if s.startswith(mode)), None)
    if row is None:
        logger.warning(
            "Focus never landed on a %s row. Stops seen: %d. Read focus-walk.txt "
            "to see what the focus order actually is.",
            mode,
            len(stops),
        )
        return out_dir

    logger.info("Focusing the first %s row again: %r", mode, row)
    focus.to_start(serial=serial)
    if not focus.focus_row(row, serial=serial):
        logger.error("Could not focus %r on a second pass — the focus order is not stable.", row)
        return out_dir

    _save_dump(out_dir, "02-row-focused", serial)
    before = {n.content_desc for n in flatten(adb.dump_ui(serial=serial)) if n.content_desc}

    logger.info("Activating the focused row with %s", focus.CENTER)
    focus.activate(serial=serial)
    trip = _save_dump(out_dir, "03-after-activate", serial)
    (out_dir / "03-after-activate-nodes.txt").write_text(
        "\n".join(_describe(trip)) + "\n", encoding="utf-8"
    )
    after = {n.content_desc for n in flatten(trip) if n.content_desc}
    logger.info(
        "Activation changed the screen: %d description(s) gone, %d new",
        len(before - after),
        len(after - before),
    )

    logger.info("Pressing Back")
    focus.back(serial=serial)
    _save_dump(out_dir, "04-after-back", serial)
    landed = focus.focused_node(serial=serial)
    logger.info("Focus after Back: %s", focus.label(landed))

    logger.info("Probe complete — read the files in %s", out_dir)
    return out_dir
