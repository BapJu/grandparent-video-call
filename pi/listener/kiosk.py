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
#
# The quality caps are not cosmetic: the Pi 5 has *no hardware video encoder*
# (unlike the Pi 4 — only a decoder, rpi-hevc-dec, exists), so every outgoing
# frame is encoded in software. At Jitsi's default 720p with simulcast — which
# encodes several resolutions at once — the CPU eventually can't keep up and
# the call degrades to "poor connection" and then drops. Capping resolution,
# frame rate and simulcast keeps it stable, and cuts 4G usage at the same time.
JITSI_CONFIG_HASH = (
    "config.prejoinPageEnabled=false"
    "&config.prejoinConfig.enabled=false"
    "&config.startWithAudioMuted=false"
    "&config.startWithVideoMuted=false"
    "&config.disableDeepLinking=true"
    # Force media through Jitsi's bridge instead of a direct peer-to-peer link.
    # In P2P the Pi's outgoing video collapsed to ~3 kbps after a few minutes
    # with *zero* packet loss — the signature of a failing direct path rather
    # than a congested one. The bridge is a server both sides simply connect
    # to, so there is no NAT path to break.
    "&config.p2p.enabled=false"
    # --- quality caps (CPU + 4G) ---
    "&config.disableSimulcast=true"
    "&config.resolution=360"
    "&config.constraints.video.height.ideal=360"
    "&config.constraints.video.height.max=360"
    "&config.constraints.video.height.min=180"
    "&config.constraints.video.frameRate.max=20"
    "&config.startVideoQuality=360"
    "&interfaceConfig.SHOW_JITSI_WATERMARK=false"
    "&interfaceConfig.SHOW_WATERMARK_FOR_GUESTS=false"
)


def build_jitsi_url(room: str) -> str:
    """Plain meet.jit.si URL (fallback when no kiosk wrapper is configured)."""
    safe_room = urllib.parse.quote(room, safe="")
    return f"{JITSI_BASE}/{safe_room}#{JITSI_CONFIG_HASH}"


def build_kiosk_url(kiosk_base: str, room: str, access_token: str | None) -> str:
    """URL of the web app's /kiosk wrapper, which embeds Jitsi via the IFrame
    API so the Pi can unmute itself and accept remote mic/camera commands.

    Room and token travel in the URL fragment, which browsers never send to the
    server — so the token stays off Vercel's logs.
    """
    params = {"room": room}
    if access_token:
        params["token"] = access_token
    return f"{kiosk_base.rstrip('/')}#{urllib.parse.urlencode(params)}"


def launch(
    room: str,
    firefox_bin: str,
    profile_dir: str,
    kiosk_base: str | None = None,
    access_token: str | None = None,
) -> subprocess.Popen:
    url = (
        build_kiosk_url(kiosk_base, room, access_token)
        if kiosk_base
        else build_jitsi_url(room)
    )
    cmd = [
        firefox_bin,
        "--kiosk",
        # Firefox's automation port, used by jitsi_probe to read the real call
        # state (participant count, mute state) out of the Jitsi page. Bound to
        # localhost only.
        "--marionette",
        "--profile",
        profile_dir,
        url,
    ]
    env = os.environ.copy()
    env["MOZ_ENABLE_WAYLAND"] = "1"
    # Log without the URL: it can carry the access token.
    logger.info("Launching kiosk room=%s via=%s", room, "wrapper" if kiosk_base else "meet.jit.si")
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


def camera_in_use(video_device: str = "/dev/video0") -> bool:
    """True when some process holds the camera open.

    This is the feedback signal for auto-unmute: Jitsi only actually opens the
    camera once video is unmuted *and* the conference has started.
    """
    try:
        return (
            subprocess.run(
                ["fuser", video_device],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            ).returncode
            == 0
        )
    except FileNotFoundError:
        logger.warning("fuser not available; cannot detect camera state")
        return False


def send_key(key: str) -> None:
    """Send a keystroke to the focused window (the kiosk) via wtype."""
    try:
        subprocess.run(
            ["wtype", key],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        logger.warning("wtype not available; cannot send keystrokes")


def kill_stray_kiosk(profile_dir: str) -> None:
    """Best-effort cleanup of a kiosk firefox left over from a crash.

    Matches on the profile path in the command line, which is unique to the
    kiosk instance.
    """
    try:
        subprocess.run(["pkill", "-f", profile_dir], check=False)
    except FileNotFoundError:
        logger.warning("pkill not available; skipping stray-kiosk cleanup")
