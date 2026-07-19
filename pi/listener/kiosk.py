"""Firefox kiosk launch/teardown helpers for the Jitsi call.

Firefox is used instead of Chromium because the Raspberry Pi OS Chromium build
routes camera capture through the xdg-desktop-portal Camera interface, which has
no backend on this labwc setup — video device enumeration hangs forever. Firefox
hits the same wall via its pipewire path, but can be switched to direct V4L2
capture with media.webrtc.camera.allow-pipewire=false (see pi/firefox/user.js).
Full investigation: docs/CAMERA-ISSUE.md.
"""

import logging
import os
import signal
import subprocess
import time
import urllib.parse

logger = logging.getLogger("visio-tv.kiosk")

JITSI_BASE = "https://meet.jit.si"

# Unknown hash params are ignored by Jitsi, so both the old and new prejoin
# config keys are included since the key has been renamed across versions.
JITSI_CONFIG_HASH = (
    "config.prejoinPageEnabled=false"
    "&config.prejoinConfig.enabled=false"
    "&config.startWithAudioMuted=false"
    "&config.startWithVideoMuted=false"
    "&config.disableDeepLinking=true"
    "&interfaceConfig.SHOW_JITSI_WATERMARK=false"
    "&interfaceConfig.SHOW_WATERMARK_FOR_GUESTS=false"
)


def build_jitsi_url(room: str) -> str:
    safe_room = urllib.parse.quote(room, safe="")
    return f"{JITSI_BASE}/{safe_room}#{JITSI_CONFIG_HASH}"


def launch(room: str, firefox_bin: str, profile_dir: str) -> subprocess.Popen:
    url = build_jitsi_url(room)
    cmd = [
        firefox_bin,
        "--kiosk",
        "--profile",
        profile_dir,
        url,
    ]
    env = os.environ.copy()
    env["MOZ_ENABLE_WAYLAND"] = "1"
    logger.info("Launching kiosk room=%s cmd=%s", room, " ".join(cmd))
    # start_new_session=True puts firefox (and its child content processes) in
    # their own process group so we can kill the whole tree.
    return subprocess.Popen(
        cmd,
        start_new_session=True,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def terminate(proc: subprocess.Popen, timeout: float = 5.0) -> None:
    if proc is None or proc.poll() is not None:
        return
    try:
        pgid = os.getpgid(proc.pid)
    except ProcessLookupError:
        return
    logger.info("Terminating kiosk pgid=%s", pgid)
    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return
        time.sleep(0.2)
    logger.warning("Kiosk pgid=%s did not exit after SIGTERM, sending SIGKILL", pgid)
    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def kill_stray_kiosk(profile_dir: str) -> None:
    """Best-effort cleanup of a kiosk firefox left over from a crash.

    Matches on the profile path in the command line, which is unique to the
    kiosk instance.
    """
    try:
        subprocess.run(["pkill", "-f", profile_dir], check=False)
    except FileNotFoundError:
        logger.warning("pkill not available; skipping stray-kiosk cleanup")
