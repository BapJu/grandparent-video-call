"""Supabase Realtime broadcast listener that drives the Jitsi kiosk.

Authenticates with a dedicated device account, joins the private Realtime
channel and reacts to two broadcast events:
  - start_call {"room": "<id>"}: launch firefox kiosk on that Jitsi room
  - end_call: tear down the kiosk

It also publishes the Pi's state (idle / in_call + room) via Realtime
presence so the family web app can show live status.

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

import kiosk
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

REALTIME_URL = (
    SUPABASE_URL.replace("https://", "wss://").replace("http://", "ws://")
    + "/realtime/v1"
)

RECONNECT_DELAYS = [5, 10, 20, 60]


class CallState:
    def __init__(self):
        self.process: subprocess.Popen | None = None
        self.timeout_task: asyncio.Task | None = None
        self.room: str | None = None
        self.channel = None


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
    if state.process is not None and state.process.poll() is None:
        logger.info(
            "Call already active (room=%s), ignoring start_call for room=%s",
            state.room,
            room,
        )
        return
    kiosk.kill_stray_kiosk(FIREFOX_PROFILE_DIR)
    state.process = kiosk.launch(room, FIREFOX_BIN, FIREFOX_PROFILE_DIR)
    state.room = room
    _cancel_timeout()
    state.timeout_task = asyncio.create_task(
        _auto_teardown_after(MAX_CALL_DURATION_SECONDS, room)
    )
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

    subscribed = asyncio.Event()
    failed = asyncio.Event()

    def _on_subscribe(status: RealtimeSubscribeStates, err: Exception | None) -> None:
        if status == RealtimeSubscribeStates.SUBSCRIBED:
            logger.info("Subscribed to channel=%s (private)", CHANNEL_NAME)
            subscribed.set()
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

    _end_call()
    logger.info("Shutting down")


if __name__ == "__main__":
    asyncio.run(main())
