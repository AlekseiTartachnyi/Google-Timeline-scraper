"""Flatten a uiautomator UI dump into ordered, inspectable element records."""

import logging
from dataclasses import dataclass
from xml.etree import ElementTree as ET

logger = logging.getLogger(__name__)


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
