"""Supabase Realtime broadcast listener — the OS side of the video frame.

Authenticates with a dedicated device account, joins the private Realtime
channel and launches/kills the Firefox kiosk on start_call/end_call. The kiosk
loads the web app's /kiosk page, which embeds the JaaS meeting through the
Jitsi IFrame API: being the local participant there, it unmutes itself and
knows the real call state (participants, chat, mute) via clean API events.

The kiosk page pushes those events back over the same private channel, and
this listener performs the OS-level actions the browser can't:
  ring / stop_ring   -> play or stop the ringtone (pw-play)
  volume {steps}     -> nudge the speaker (wpctl)
  call_busy/call_empty -> cancel or start the "left alone" hang-up countdown
  call_ended         -> tear the call down

It also runs the photo-frame slideshow while idle and publishes presence.

Designed to be started by labwc autostart (via a systemd --user unit) inside
the graphical session, so it inherits the Wayland socket needed to spawn a
GUI child process.
"""

import asyncio
import logging
import os
import signal
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from realtime import AsyncRealtimeClient, RealtimeSubscribeStates

import audio
import kiosk
import photos
import ringtone
import slideshow
import supa_auth

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("visio-tv.listener")

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(ENV_PATH)

SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SUPABASE_ANON_KEY = os.environ["SUPABASE_ANON_KEY"]
SUPABASE_DEVICE_EMAIL = os.environ["SUPABASE_DEVICE_EMAIL"]
SUPABASE_DEVICE_PASSWORD = os.environ["SUPABASE_DEVICE_PASSWORD"]
CHANNEL_NAME = os.environ.get("SUPABASE_CHANNEL", "visio-tv-calls")
MAX_CALL_DURATION_SECONDS = int(os.environ.get("MAX_CALL_DURATION_SECONDS", "5400"))
FIREFOX_BIN = os.environ.get("FIREFOX_BIN", "/usr/bin/firefox")
FIREFOX_PROFILE_DIR = os.environ.get(
    "FIREFOX_PROFILE_DIR", "/home/julienne/.config/visio-tv-ff"
)
# URL of the web app's /kiosk page (embeds JaaS via the IFrame API). The Pi
# joins as moderator, so the room starts on its own — no host login needed.
KIOSK_URL = os.environ.get("KIOSK_URL", "").strip()
# Hang up this long after the last remote participant leaves, so the Pi never
# sits alone in a room with its camera and mic live.
HANGUP_WHEN_ALONE_AFTER = float(os.environ.get("HANGUP_WHEN_ALONE_AFTER", "60"))
# How often to check that the kiosk is still alive during a call.
KIOSK_WATCH_INTERVAL = float(os.environ.get("KIOSK_WATCH_INTERVAL", "5"))

# --- Photo frame -----------------------------------------------------------
SLIDESHOW_ENABLED = os.environ.get("SLIDESHOW_ENABLED", "true").lower() not in (
    "0",
    "false",
    "no",
)
PHOTOS_DIR = os.environ.get("PHOTOS_DIR", "/home/julienne/visio-tv/photos")
SLIDESHOW_INTERVAL = float(os.environ.get("SLIDESHOW_INTERVAL", "8"))
# Outside this window the video signal is cut so the screen goes to standby.
SLIDESHOW_START = os.environ.get("SLIDESHOW_START", "09:00")
SLIDESHOW_END = os.environ.get("SLIDESHOW_END", "21:00")
# Safety net in case a photos_changed broadcast is ever missed.
PHOTO_SYNC_INTERVAL = float(os.environ.get("PHOTO_SYNC_INTERVAL", "21600"))

# --- Ringtone --------------------------------------------------------------
# Rings when the caller actually joins, to bring her to the screen. Nobody
# "answers" on this end, so it just gives up after a while like a phone would.
RINGTONE_ENABLED = os.environ.get("RINGTONE_ENABLED", "true").lower() not in (
    "0",
    "false",
    "no",
)
RINGTONE_FILE = os.environ.get("RINGTONE_FILE", "/home/julienne/visio-tv/ringtone.wav")
RINGTONE_DURATION = float(os.environ.get("RINGTONE_DURATION", "45"))

# --- Volume by chat --------------------------------------------------------
# The kiosk page parses +/-/plus/moins from the Jitsi chat and sends the number
# of steps; this is how many percent each step moves the speaker.
VOLUME_STEP = int(os.environ.get("VOLUME_STEP", "10"))

REALTIME_URL = (
    SUPABASE_URL.replace("https://", "wss://").replace("http://", "ws://")
    + "/realtime/v1"
)

RECONNECT_DELAYS = [5, 10, 20, 60]


class CallState:
    def __init__(self):
        self.process: subprocess.Popen | None = None
        self.timeout_task: asyncio.Task | None = None
        self.watch_task: asyncio.Task | None = None
        self.ring_task: asyncio.Task | None = None
        self.hangup_task: asyncio.Task | None = None
        self.room: str | None = None
        self.channel = None
        # Current Supabase access token, handed to the kiosk page so it can
        # join the private channel and receive mic/camera commands.
        self.access_token: str | None = None
        # Photo frame
        self.slideshow_proc: subprocess.Popen | None = None
        self.photos_dirty = False  # a sync changed files: imv needs restarting


state = CallState()


async def publish_presence() -> None:
    """Publish the Pi's current state.

    Note: realtime-py's track() appends a presence entry instead of replacing
    the previous one, and untrack() does not reliably clear it, so several
    entries can live under the 'pi' key. Consumers must therefore use the most
    recent one (highest 'since') — see web/app/components/CallPanel.tsx.
    """
    channel = state.channel
    if channel is None:
        return
    try:
        await channel.track(
            {
                "device": "pi",
                "status": "in_call" if state.room else "idle",
                "room": state.room,
                "since": datetime.now(timezone.utc).isoformat(),
            }
        )
    except Exception:
        logger.exception("Failed to publish presence")


async def _broadcast(event: str, payload: dict | None = None) -> None:
    """Send a broadcast to the family app (best effort)."""
    channel = state.channel
    if channel is None:
        return
    try:
        await channel.send_broadcast(event, payload or {})
    except Exception:
        logger.debug("broadcast %s failed", event, exc_info=True)


async def _ring_with_signal() -> None:
    """Play the ringtone and tell the app when it starts/stops, so the app can
    show that it's ringing (and must be stopped manually)."""
    await _broadcast("ringing", {"active": True})
    try:
        await ringtone.ring(RINGTONE_FILE, RINGTONE_DURATION)
    finally:
        await _broadcast("ringing", {"active": False})


async def _hangup_after_alone(room: str) -> None:
    """Hang up if the Pi is left alone in the room for too long.

    Triggered by the kiosk page's `call_empty`; cancelled by `call_busy` when
    someone (re)joins. This stops the Pi sitting alone with camera and mic live
    (privacy + 4G) if the caller closes their tab instead of hanging up.
    """
    try:
        await asyncio.sleep(HANGUP_WHEN_ALONE_AFTER)
    except asyncio.CancelledError:
        return
    if state.room == room and state.process is not None:
        logger.info("Call empty for %ss — hanging up (room=%s)", HANGUP_WHEN_ALONE_AFTER, room)
        _end_call()


def _within_slideshow_window(now: datetime | None = None) -> bool:
    """True when the current local time is inside the photo-frame window.

    Handles windows that wrap past midnight (e.g. 21:00 → 09:00).
    """
    now = now or datetime.now()
    try:
        start_h, start_m = (int(x) for x in SLIDESHOW_START.split(":"))
        end_h, end_m = (int(x) for x in SLIDESHOW_END.split(":"))
    except ValueError:
        logger.warning(
            "Invalid SLIDESHOW_START/END (%r/%r) — keeping the frame on",
            SLIDESHOW_START,
            SLIDESHOW_END,
        )
        return True
    minutes = now.hour * 60 + now.minute
    start = start_h * 60 + start_m
    end = end_h * 60 + end_m
    if start == end:
        return True
    return start <= minutes < end if start < end else (minutes >= start or minutes < end)


def _stop_slideshow() -> None:
    if state.slideshow_proc is not None:
        slideshow.stop(state.slideshow_proc)
        state.slideshow_proc = None


async def sync_photos() -> None:
    """Refresh the local photo cache; flag the slideshow for restart if changed."""
    if not SLIDESHOW_ENABLED or not state.access_token:
        return
    added, removed = await asyncio.to_thread(
        photos.sync, SUPABASE_URL, SUPABASE_ANON_KEY, state.access_token, PHOTOS_DIR
    )
    if added or removed:
        # imv freezes its file list at launch, so it must be restarted to pick
        # up new or deleted photos.
        state.photos_dirty = True


async def _slideshow_loop() -> None:
    """Run the photo frame whenever the Pi is idle and inside the time window.

    A call always wins: the kiosk needs the screen to itself.
    """
    last_sync = 0.0
    loop = asyncio.get_running_loop()

    while True:
        try:
            if state.access_token and loop.time() - last_sync > PHOTO_SYNC_INTERVAL:
                await sync_photos()
                last_sync = loop.time()

            in_call = state.process is not None
            running = (
                state.slideshow_proc is not None and state.slideshow_proc.poll() is None
            )

            if in_call:
                # The call owns the screen.
                if running:
                    _stop_slideshow()
                slideshow.display_on()
            elif not _within_slideshow_window():
                if running:
                    _stop_slideshow()
                slideshow.display_off()
            elif await asyncio.to_thread(photos.count_local, PHOTOS_DIR) == 0:
                if running:
                    _stop_slideshow()
            else:
                if running and state.photos_dirty:
                    _stop_slideshow()
                    running = False
                if not running:
                    slideshow.display_on()
                    state.slideshow_proc = slideshow.start(PHOTOS_DIR, SLIDESHOW_INTERVAL)
                    state.photos_dirty = False
        except Exception:
            logger.exception("Slideshow loop error")

        await asyncio.sleep(30)


async def _watch_kiosk(room: str, proc: subprocess.Popen) -> None:
    """Notice when the kiosk dies on its own (crash, or Firefox quitting).

    Without this the call state would stay 'in_call' until the max-duration
    timeout, so the app would show a phantom call, the auto-unmute loop would
    keep firing keystrokes at whatever window has focus, and the dead process
    would linger as a zombie (poll() also reaps it).
    """
    while True:
        await asyncio.sleep(KIOSK_WATCH_INTERVAL)
        if state.room != room or state.process is not proc:
            return  # call already ended or replaced
        rc = proc.poll()
        if rc is None:
            continue
        logger.warning(
            "Kiosk exited on its own (code=%s) during room=%s — clearing call state",
            rc,
            room,
        )
        state.process = None
        state.room = None
        _cancel_timeout()
        _cancel_ring()
        _cancel_hangup()
        await publish_presence()
        return


def _cancel_ring() -> None:
    if state.ring_task is not None and not state.ring_task.done():
        state.ring_task.cancel()
    state.ring_task = None


def _cancel_watch() -> None:
    if state.watch_task is not None and not state.watch_task.done():
        state.watch_task.cancel()
    state.watch_task = None


def _cancel_hangup() -> None:
    if state.hangup_task is not None and not state.hangup_task.done():
        state.hangup_task.cancel()
    state.hangup_task = None


def _cancel_timeout() -> None:
    if state.timeout_task is not None and not state.timeout_task.done():
        state.timeout_task.cancel()
    state.timeout_task = None


async def _auto_teardown_after(seconds: int, room: str) -> None:
    try:
        await asyncio.sleep(seconds)
    except asyncio.CancelledError:
        return
    logger.warning("Max call duration reached for room=%s, tearing down", room)
    _end_call()


def _start_call(room: str) -> None:
    if not KIOSK_URL:
        logger.error("KIOSK_URL not set — cannot start a call")
        return
    if state.process is not None and state.process.poll() is None:
        logger.info(
            "Call already active (room=%s), ignoring start_call for room=%s",
            state.room,
            room,
        )
        return
    # Hand the screen over to the call immediately rather than waiting for the
    # slideshow loop's next tick.
    _stop_slideshow()
    slideshow.display_on()

    kiosk.kill_stray_kiosk(FIREFOX_PROFILE_DIR)
    try:
        state.process = kiosk.launch(
            room,
            FIREFOX_BIN,
            FIREFOX_PROFILE_DIR,
            kiosk_base=KIOSK_URL,
            access_token=state.access_token,
        )
    except OSError:
        # e.g. FIREFOX_BIN missing: stay 'idle' rather than advertising a call
        # that does not exist.
        logger.exception("Failed to launch the kiosk for room=%s", room)
        state.process = None
        state.room = None
        asyncio.create_task(publish_presence())
        return
    state.room = room
    _cancel_timeout()
    state.timeout_task = asyncio.create_task(
        _auto_teardown_after(MAX_CALL_DURATION_SECONDS, room)
    )
    _cancel_ring()
    _cancel_hangup()
    _cancel_watch()
    state.watch_task = asyncio.create_task(_watch_kiosk(room, state.process))
    asyncio.create_task(publish_presence())
    logger.info("start_call handled room=%s pid=%s", room, state.process.pid)


def _end_call() -> None:
    if state.process is None:
        logger.info("end_call received but no active call")
        return
    kiosk.terminate(state.process)
    logger.info("end_call handled, room=%s", state.room)
    state.process = None
    state.room = None
    _cancel_timeout()
    _cancel_watch()
    _cancel_ring()
    _cancel_hangup()
    try:
        asyncio.get_running_loop()
        asyncio.create_task(publish_presence())
    except RuntimeError:
        pass  # called outside the loop during final shutdown


def _on_start_call(payload: dict) -> None:
    room = (payload.get("payload") or {}).get("room")
    if not room:
        logger.error("start_call event missing 'room' in payload: %s", payload)
        return
    _start_call(room)


def _on_end_call(_payload: dict) -> None:
    _end_call()


def _on_photos_changed(_payload: dict) -> None:
    """The app added or removed photos: refresh the cache right away."""
    asyncio.create_task(sync_photos())


# --- events pushed by the kiosk page (its embedded Jitsi) ------------------

def _on_ring(_payload: dict) -> None:
    if not RINGTONE_ENABLED or state.process is None:
        return
    _cancel_ring()
    state.ring_task = asyncio.create_task(_ring_with_signal())
    logger.info("Ringing (caller joined)")


def _on_stop_ring(_payload: dict) -> None:
    if state.ring_task is not None and not state.ring_task.done():
        logger.info("Stopping the ringtone (chat message)")
    _cancel_ring()


def _on_volume(payload: dict) -> None:
    steps = (payload.get("payload") or {}).get("steps")
    if isinstance(steps, int) and steps:
        asyncio.create_task(asyncio.to_thread(audio.nudge, steps * VOLUME_STEP))


def _on_call_busy(_payload: dict) -> None:
    """Someone is in the room: cancel any pending "left alone" hang-up."""
    if state.hangup_task is not None:
        logger.info("Someone (re)joined — cancelling hang-up countdown")
    _cancel_hangup()


def _on_call_empty(_payload: dict) -> None:
    """The Pi is alone: start the grace countdown before hanging up."""
    if state.process is None or state.room is None:
        return
    if state.hangup_task is not None and not state.hangup_task.done():
        return  # already counting down
    logger.info("Everyone left, hanging up in %ss unless someone comes back", HANGUP_WHEN_ALONE_AFTER)
    state.hangup_task = asyncio.create_task(_hangup_after_alone(state.room))


def _on_call_ended(_payload: dict) -> None:
    _end_call()


async def _refresh_auth_forever(client: AsyncRealtimeClient, expires_in: int) -> None:
    """Re-login periodically; set_auth() re-authorizes the joined channel in place."""
    while True:
        delay = min(2700, max(60, int(expires_in * 0.75)))
        await asyncio.sleep(delay)
        try:
            auth = await asyncio.to_thread(
                supa_auth.login,
                SUPABASE_URL,
                SUPABASE_ANON_KEY,
                SUPABASE_DEVICE_EMAIL,
                SUPABASE_DEVICE_PASSWORD,
            )
            expires_in = int(auth.get("expires_in", 3600))
            state.access_token = auth["access_token"]
            await client.set_auth(auth["access_token"])
            logger.info("Auth token refreshed (next in ~%ss)", min(2700, int(expires_in * 0.75)))
        except Exception:
            logger.exception("Token refresh failed, retrying in 60s")
            expires_in = 80  # retry soon; server drop is caught by the outer loop


async def run_once() -> None:
    auth = await asyncio.to_thread(
        supa_auth.login,
        SUPABASE_URL,
        SUPABASE_ANON_KEY,
        SUPABASE_DEVICE_EMAIL,
        SUPABASE_DEVICE_PASSWORD,
    )
    logger.info("Device login OK (%s)", SUPABASE_DEVICE_EMAIL)
    state.access_token = auth["access_token"]

    client = AsyncRealtimeClient(REALTIME_URL, SUPABASE_ANON_KEY)
    await client.connect()
    # Must be set before subscribe so the join payload carries the JWT.
    await client.set_auth(auth["access_token"])

    channel = client.channel(
        CHANNEL_NAME,
        {"config": {"private": True, "presence": {"key": "pi"}}},
    )
    channel.on_broadcast("start_call", _on_start_call)
    channel.on_broadcast("end_call", _on_end_call)
    channel.on_broadcast("photos_changed", _on_photos_changed)
    # Events pushed by the kiosk page during a call.
    channel.on_broadcast("ring", _on_ring)
    channel.on_broadcast("stop_ring", _on_stop_ring)
    channel.on_broadcast("volume", _on_volume)
    channel.on_broadcast("call_busy", _on_call_busy)
    channel.on_broadcast("call_empty", _on_call_empty)
    channel.on_broadcast("call_ended", _on_call_ended)

    subscribed = asyncio.Event()
    failed = asyncio.Event()

    def _on_subscribe(status: RealtimeSubscribeStates, err: Exception | None) -> None:
        if status == RealtimeSubscribeStates.SUBSCRIBED:
            logger.info("Subscribed to channel=%s (private)", CHANNEL_NAME)
            subscribed.set()
            # On a *re*-subscribe (realtime-py reconnected the socket on its
            # own), the server has dropped our presence — re-publish it, or the
            # app would keep showing the Pi offline. state.channel is only set
            # after the initial subscribe, so this skips the first time (which
            # run_once publishes explicitly just below).
            if state.channel is not None:
                logger.info("Re-subscribed after reconnect — republishing presence")
                asyncio.create_task(publish_presence())
        elif status in (
            RealtimeSubscribeStates.CHANNEL_ERROR,
            RealtimeSubscribeStates.TIMED_OUT,
        ):
            logger.error("Subscription failed status=%s err=%s", status, err)
            failed.set()

    await channel.subscribe(_on_subscribe)

    sub_task = asyncio.create_task(subscribed.wait())
    fail_task = asyncio.create_task(failed.wait())
    done, pending = await asyncio.wait(
        {sub_task, fail_task}, return_when=asyncio.FIRST_COMPLETED, timeout=30
    )
    for t in pending:
        t.cancel()
    if not subscribed.is_set():
        raise RuntimeError("channel subscribe failed or timed out")

    state.channel = channel
    await publish_presence()
    await sync_photos()

    refresh_task = asyncio.create_task(
        _refresh_auth_forever(client, int(auth.get("expires_in", 3600)))
    )
    try:
        # The client handles incoming messages via its own background task;
        # this coroutine just needs to stay alive until the connection drops.
        await asyncio.Event().wait()
    finally:
        refresh_task.cancel()
        state.channel = None


async def main() -> None:
    kiosk.kill_stray_kiosk(FIREFOX_PROFILE_DIR)

    loop = asyncio.get_running_loop()
    stop = asyncio.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)

    slideshow_task = (
        asyncio.create_task(_slideshow_loop()) if SLIDESHOW_ENABLED else None
    )

    delay_idx = 0
    while not stop.is_set():
        run_task = asyncio.create_task(run_once())
        stop_task = asyncio.create_task(stop.wait())
        done, pending = await asyncio.wait(
            {run_task, stop_task}, return_when=asyncio.FIRST_COMPLETED
        )
        for t in pending:
            t.cancel()

        if stop.is_set():
            run_task.cancel()
            break

        exc = run_task.exception() if run_task.done() else None
        if exc is not None:
            logger.exception("Listener loop crashed, will retry", exc_info=exc)
            delay = RECONNECT_DELAYS[min(delay_idx, len(RECONNECT_DELAYS) - 1)]
            delay_idx += 1
            await asyncio.sleep(delay)
        else:
            delay_idx = 0

    if slideshow_task is not None:
        slideshow_task.cancel()
    _stop_slideshow()
    _end_call()
    logger.info("Shutting down")


if __name__ == "__main__":
    asyncio.run(main())
