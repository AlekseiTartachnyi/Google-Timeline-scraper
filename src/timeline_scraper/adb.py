"""ADB wrappers — thin subprocess layer for all phone interactions."""

import logging
import subprocess
import tempfile
from pathlib import Path
from xml.etree import ElementTree as ET

logger = logging.getLogger(__name__)

_ADB = "adb"


class ADBError(RuntimeError):
    """Raised when an adb command returns a non-zero exit code."""


def _run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run an adb command and return the CompletedProcess."""
    cmd = [_ADB, *args]
    logger.debug("$ %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True)
    if check and result.returncode != 0:
        raise ADBError(
            f"adb {' '.join(args)} exited {result.returncode}: "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
    return result


def devices() -> list[str]:
    """Return serials of all connected devices reported as 'device' by adb."""
    result = _run("devices")
    serials: list[str] = []
    for line in result.stdout.strip().splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            serials.append(parts[0])
    return serials


def shell(command: str, serial: str | None = None) -> str:
    """Run a shell command on the device and return stdout."""
    prefix = ["-s", serial] if serial else []
    result = _run(*prefix, "shell", command)
    return result.stdout


def tap(x: int, y: int, serial: str | None = None) -> None:
    """Tap the screen at pixel coordinates (x, y)."""
    shell(f"input tap {x} {y}", serial=serial)


def swipe(
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    duration_ms: int = 300,
    serial: str | None = None,
) -> None:
    """Swipe from (x1, y1) to (x2, y2) over duration_ms milliseconds."""
    shell(f"input swipe {x1} {y1} {x2} {y2} {duration_ms}", serial=serial)


def dump_ui(serial: str | None = None) -> ET.Element:
    """Dump the UI hierarchy and return the parsed XML root element.

    Writes the dump to /sdcard/window_dump.xml on the device, pulls it to a
    local temp file, parses it, and deletes the temp file.
    """
    remote = "/sdcard/window_dump.xml"
    shell(f"uiautomator dump {remote}", serial=serial)
    prefix = ["-s", serial] if serial else []
    with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as tmp:
        local = tmp.name
    try:
        _run(*prefix, "pull", remote, local)
        return ET.parse(local).getroot()
    finally:
        Path(local).unlink(missing_ok=True)


def wake_screen(serial: str | None = None) -> None:
    """Wake the screen if it is off."""
    shell("input keyevent KEYCODE_WAKEUP", serial=serial)


def is_locked(serial: str | None = None) -> bool:
    """Return True if the keyguard (lock screen) is currently showing."""
    out = shell("dumpsys keyguard", serial=serial)
    return "isKeyguardShowing=true" in out or "mKeyguardShowing=true" in out


def screencap(serial: str | None = None) -> bytes:
    """Capture a screenshot and return raw PNG bytes.

    Uses exec-out to stream directly without writing to /sdcard.
    """
    prefix = ["-s", serial] if serial else []
    result = subprocess.run(
        [_ADB, *prefix, "exec-out", "screencap", "-p"],
        capture_output=True,
    )
    if result.returncode != 0:
        raise ADBError(f"screencap failed: {result.stderr.decode().strip()}")
    return result.stdout
