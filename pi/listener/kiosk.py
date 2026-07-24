"""Firefox kiosk launch/teardown helpers.

The Pi loads the web app's /kiosk page, which embeds the JaaS meeting via the
Jitsi IFrame API (call config, quality caps and unmute all live there now). So
this module just launches Firefox at that page and tears it down.

Firefox is used instead of Chromium because the Raspberry Pi OS Chromium build
routes camera capture through the xdg-desktop-portal Camera interface, which has
no backend on this labwc setup — video device enumeration hangs forever. Firefox
can be switched to direct V4L2 capture with media.webrtc.camera.allow-pipewire=
false (see pi/firefox/user.js). Full investigation: docs/CAMERA-ISSUE.md.
"""

import logging
import os
import signal
import subprocess
import time
import urllib.parse

logger = logging.getLogger("visio-tv.kiosk")


def build_kiosk_url(kiosk_base: str, room: str, access_token: str | None) -> str:
    """URL of the web app's /kiosk page.

    Room and token travel in the URL fragment, which browsers never send to the
    server — so the token stays off Vercel's logs.

    A per-launch cache-buster (?v=<timestamp>) forces Firefox to fetch the
    latest deployed page every call, so the unattended Pi can't get stuck on a
    stale cached version after a deploy.
    """
    params = {"room": room}
    if access_token:
        params["token"] = access_token
    base = kiosk_base.rstrip("/")
    sep = "&" if "?" in base else "?"
    return f"{base}{sep}v={int(time.time())}#{urllib.parse.urlencode(params)}"


def launch(
    room: str,
    firefox_bin: str,
    profile_dir: str,
    kiosk_base: str,
    access_token: str | None = None,
) -> subprocess.Popen:
    url = build_kiosk_url(kiosk_base, room, access_token)
    cmd = [firefox_bin, "--kiosk", "--profile", profile_dir, url]
    env = os.environ.copy()
    env["MOZ_ENABLE_WAYLAND"] = "1"
    # Log without the URL: it carries the access token.
    logger.info("Launching kiosk for room=%s", room)
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
