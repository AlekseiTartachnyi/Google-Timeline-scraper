"""ADB wrappers — thin subprocess layer for all phone interactions."""

import logging
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from xml.etree import ElementTree as ET

logger = logging.getLogger(__name__)

# Where platform-tools ends up when it is installed but never added to PATH.
_ADB_FALLBACKS = (
    r"%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe",
    r"%USERPROFILE%\scoop\shims\adb.exe",
    r"%ProgramData%\chocolatey\bin\adb.exe",
    r"%ProgramFiles%\platform-tools\adb.exe",
    r"%USERPROFILE%\platform-tools\adb.exe",
    r"C:\platform-tools\adb.exe",
    "~/Android/Sdk/platform-tools/adb",
    "~/Library/Android/sdk/platform-tools/adb",
    "/usr/lib/android-sdk/platform-tools/adb",
    "/usr/local/bin/adb",
)

_resolved_adb: str | None = None


class ADBError(RuntimeError):
    """Raised when an adb command fails, or adb itself cannot be found."""


def adb_path() -> str:
    """Return the adb executable to run, looking beyond PATH if need be.

    PATH is the normal answer, but a terminal opened before platform-tools was
    installed — or one that never had it — does not carry it, and the raw
    "The system cannot find the file specified" says nothing useful. The ADB
    environment variable wins if it is set; otherwise the usual install
    locations are checked before giving up.
    """
    global _resolved_adb
    if _resolved_adb:
        return _resolved_adb

    override = os.environ.get("ADB")
    if override:
        found = shutil.which(override) or (override if Path(override).is_file() else None)
        if not found:
            raise ADBError(f"ADB is set to {override!r}, but there is no such executable")
        logger.info("Using adb from the ADB environment variable: %s", found)
        _resolved_adb = found
        return _resolved_adb

    found = shutil.which("adb")
    if found:
        _resolved_adb = found
        return _resolved_adb

    for candidate in _ADB_FALLBACKS:
        expanded = Path(os.path.expandvars(os.path.expanduser(candidate)))
        if "%" in str(expanded):
            continue
        if expanded.is_file():
            logger.warning("adb is not on PATH; using %s", expanded)
            _resolved_adb = str(expanded)
            return _resolved_adb

    raise ADBError(
        "adb was not found. Install Android platform-tools and add the folder "
        "holding adb.exe to PATH, or point this run at it with the ADB "
        r"environment variable, e.g. set ADB=C:\platform-tools\adb.exe"
    )


def _run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run an adb command and return the CompletedProcess."""
    cmd = [adb_path(), *args]
    logger.debug("$ %s", " ".join(cmd))
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
    except OSError as exc:
        raise ADBError(f"Could not run {cmd[0]}: {exc}") from exc
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


def keyevent(key: str, serial: str | None = None) -> None:
    """Send a key event by name, e.g. 'KEYCODE_DPAD_DOWN'."""
    shell(f"input keyevent {key}", serial=serial)


def dump_ui_xml(serial: str | None = None) -> str:
    """Dump the UI hierarchy and return the raw XML text.

    Writes the dump to /sdcard/window_dump.xml on the device, pulls it to a
    local temp file, reads it, and deletes the temp file. The text is returned
    rather than the parsed tree so a screen that defeated the code can be
    saved exactly as it was read.
    """
    remote = "/sdcard/window_dump.xml"
    shell(f"uiautomator dump {remote}", serial=serial)
    prefix = ["-s", serial] if serial else []
    with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as tmp:
        local = tmp.name
    try:
        _run(*prefix, "pull", remote, local)
        return Path(local).read_text(encoding="utf-8", errors="replace")
    finally:
        Path(local).unlink(missing_ok=True)


def dump_ui(serial: str | None = None) -> ET.Element:
    """Dump the UI hierarchy and return the parsed XML root element."""
    return ET.fromstring(dump_ui_xml(serial=serial))


def wake_screen(serial: str | None = None) -> None:
    """Wake the screen if it is off."""
    shell("input keyevent KEYCODE_WAKEUP", serial=serial)


def is_locked(serial: str | None = None) -> bool:
    """Return True if the lock screen is currently showing.

    Tries multiple detection methods because the output format of dumpsys
    varies across Android versions.
    """
    keyguard = shell("dumpsys keyguard", serial=serial)
    if any(m in keyguard for m in ("isKeyguardShowing=true", "mKeyguardShowing=true", "showing=true")):
        return True

    window = shell("dumpsys window", serial=serial)
    if "mDreamingLockscreen=true" in window or "isStatusBarKeyguard=true" in window:
        return True

    power = shell("dumpsys power", serial=serial)
    if "mWakefulness=Asleep" in power or "mWakefulness=Dozing" in power:
        return True

    logger.debug("Lock detection found no match; assuming unlocked")
    return False


def screencap(serial: str | None = None) -> bytes:
    """Capture a screenshot and return raw PNG bytes.

    Uses exec-out to stream directly without writing to /sdcard.
    """
    prefix = ["-s", serial] if serial else []
    try:
        result = subprocess.run(
            [adb_path(), *prefix, "exec-out", "screencap", "-p"],
            capture_output=True,
        )
    except OSError as exc:
        raise ADBError(f"Could not run adb: {exc}") from exc
    if result.returncode != 0:
        raise ADBError(f"screencap failed: {result.stderr.decode().strip()}")
    return result.stdout


def screen_size(serial: str | None = None) -> tuple[int, int]:
    """Return the device screen size as (width, height) in pixels."""
    output = shell("wm size", serial=serial)
    match = re.search(r"(\d+)x(\d+)", output)
    if not match:
        raise ADBError(f"Could not read screen size from: {output.strip()!r}")
    return int(match.group(1)), int(match.group(2))
