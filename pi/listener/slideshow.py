"""Photo-frame slideshow (imv) and display power control (wlopm).

imv is used rather than a browser page: it's a native Wayland viewer, so the
frame costs ~4 W instead of the ~8 W a permanently-open Firefox would draw —
and on this setup the screen is what dominates consumption anyway, which is
why display_off() exists.

Note the display is an old VGA monitor behind an HDMI→VGA adapter, so HDMI-CEC
can't be used to control it. Cutting the video signal is enough: the monitor
drops into its own "no signal" standby.
"""

import logging
import os
import shutil
import signal
import subprocess
import time

logger = logging.getLogger("visio-tv.slideshow")

# Debian ships imv-wayland/imv-x11 rather than a plain `imv`, so pick whichever
# exists (Wayland first: labwc is the compositor here).
_IMV_CANDIDATES = ("imv-wayland", "imv")


def find_viewer(preferred: str = "") -> str | None:
    for name in (preferred, *_IMV_CANDIDATES):
        if name and shutil.which(name):
            return name
    return None


def start(
    photos_dir: str, interval: float, imv_bin: str = ""
) -> subprocess.Popen | None:
    viewer = find_viewer(imv_bin)
    if viewer is None:
        logger.error("No imv binary found — install it with: sudo apt install imv")
        return None
    cmd = [viewer, "-f", "-r", "-t", str(int(interval)), photos_dir]
    logger.info("Starting slideshow with %s (%ss per photo)", viewer, int(interval))
    try:
        return subprocess.Popen(
            cmd,
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as e:
        logger.error("Could not start %s: %s", viewer, e)
        return None


def stop(proc: subprocess.Popen | None, timeout: float = 5.0) -> None:
    if proc is None or proc.poll() is not None:
        return
    try:
        pgid = os.getpgid(proc.pid)
    except ProcessLookupError:
        return
    logger.info("Stopping slideshow")
    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return
        time.sleep(0.2)
    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def _outputs() -> list[str]:
    """Wayland output names, read from wlopm (e.g. HDMI-A-1, or NOOP-1 headless)."""
    try:
        result = subprocess.run(
            ["wlopm"], capture_output=True, text=True, timeout=5, check=False
        )
    except (FileNotFoundError, subprocess.SubprocessError) as e:
        logger.warning("wlopm unavailable: %s", e)
        return []
    names = []
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            names.append(parts[0])
    return names


def _set_power(on: bool) -> None:
    flag = "--on" if on else "--off"
    for output in _outputs():
        try:
            subprocess.run([("wlopm"), flag, output], check=False, timeout=5)
        except (FileNotFoundError, subprocess.SubprocessError) as e:
            logger.warning("Failed to switch %s %s: %s", output, flag, e)
            return


def display_on() -> None:
    _set_power(True)


def display_off() -> None:
    _set_power(False)
