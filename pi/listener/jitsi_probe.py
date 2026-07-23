"""Read (and drive) the Jitsi page state through Firefox's Marionette port.

meet.jit.si can't be embedded (5-minute cap) and exposes no server-side room
API, so the only reliable way to know what the call is actually doing is to
ask the page itself. Firefox's built-in automation server gives us exactly
that: the kiosk is launched with --marionette and this module evaluates a
small script against Jitsi's Redux store.

That yields the two things blind keystrokes could never give us:
  * how many remote participants are in the room (so the Pi can hang up when
    it is left alone)
  * the real mic/camera mute state (so unmuting is idempotent)

Everything here is blocking; call it from asyncio via asyncio.to_thread.
"""

import json
import logging
import socket

logger = logging.getLogger("visio-tv.jitsi")

MARIONETTE_HOST = "127.0.0.1"
MARIONETTE_PORT = 2828

# Jitsi's page globals live behind Firefox's Xray wrappers, hence
# window.wrappedJSObject. Returns a JSON string so we don't depend on how
# Marionette serialises objects.
_STATE_SCRIPT = """
const w = window.wrappedJSObject || window;
const out = { ready: false };
try {
  const st = w.APP.store.getState();
  const p = st['features/base/participants'];
  const remote = p.remote;
  out.remote = remote && remote.size !== undefined
    ? remote.size
    : Object.keys(remote || {}).length;
  out.audioMuted = !!st['features/base/media'].audio.muted;
  out.videoMuted = st['features/base/media'].video.muted !== 0;
  // Chat drives two things from the Jitsi app (handier than switching back to
  // the family app mid-call): silencing the ringtone, and volume via +/-.
  const chat = st['features/chat'];
  const msgs = chat && chat.messages ? chat.messages : [];
  out.messages = msgs.length;
  // Just the text of the last few, newest last, for command parsing.
  out.lastMessages = msgs.slice(-5).map(m => String(m.message || ''));
  out.ready = true;
} catch (e) {
  out.error = String(e);
}
return JSON.stringify(out);
"""


class ProbeError(RuntimeError):
    pass


class _Marionette:
    """Minimal Marionette client (length-prefixed JSON over TCP)."""

    def __init__(self, timeout: float = 8.0):
        self._sock = socket.create_connection(
            (MARIONETTE_HOST, MARIONETTE_PORT), timeout=timeout
        )
        self._sock.settimeout(timeout)
        self._msgid = 0
        self._recv()  # handshake
        self._command("WebDriver:NewSession", {})

    def _recv(self):
        length = b""
        while not length.endswith(b":"):
            chunk = self._sock.recv(1)
            if not chunk:
                raise ProbeError("marionette closed the connection")
            length += chunk
        remaining = int(length[:-1])
        buf = b""
        while len(buf) < remaining:
            part = self._sock.recv(remaining - len(buf))
            if not part:
                raise ProbeError("marionette closed mid-message")
            buf += part
        return json.loads(buf)

    def _command(self, name: str, params: dict):
        self._msgid += 1
        payload = json.dumps([0, self._msgid, name, params]).encode()
        self._sock.sendall(str(len(payload)).encode() + b":" + payload)
        message = self._recv()
        # Response shape: [1, msgid, error, result]
        if isinstance(message, list) and len(message) >= 4 and message[2]:
            raise ProbeError(f"{name} failed: {message[2]}")
        return message[3] if isinstance(message, list) else message

    def execute(self, script: str):
        return self._command("WebDriver:ExecuteScript", {"script": script, "args": []})

    def close(self):
        try:
            self._sock.close()
        except OSError:
            pass


def _run(script: str):
    client = None
    try:
        client = _Marionette()
        return client.execute(script)
    finally:
        if client is not None:
            client.close()


def get_state() -> dict | None:
    """Current call state, or None when the page isn't reachable/ready.

    Returns {"remote": int, "audioMuted": bool, "videoMuted": bool,
    "messages": int, "lastMessages": list[str]}.
    """
    try:
        result = _run(_STATE_SCRIPT)
    except (ProbeError, OSError) as e:
        logger.debug("Jitsi probe unavailable: %s", e)
        return None

    raw = result.get("value") if isinstance(result, dict) else result
    try:
        state = json.loads(raw)
    except (TypeError, ValueError):
        logger.debug("Jitsi probe returned unexpected payload: %r", raw)
        return None

    if not state.get("ready"):
        # Normal while the page is still loading or waiting for a moderator.
        logger.debug("Jitsi not ready yet: %s", state.get("error"))
        return None
    return state


def set_muted(audio: bool | None = None, video: bool | None = None) -> bool:
    """Set mic/camera to an explicit state (no blind toggling).

    Jitsi's keyboard shortcuts are toggles, so we first read the real state
    and only send the keystroke when it actually needs to change.
    """
    state = get_state()
    if state is None:
        return False
    try:
        if audio is not None and state["audioMuted"] != audio:
            _run("const w = window.wrappedJSObject || window; w.APP.conference.toggleAudioMuted(); return 1;")
        if video is not None and state["videoMuted"] != video:
            _run("const w = window.wrappedJSObject || window; w.APP.conference.toggleVideoMuted(); return 1;")
        return True
    except (ProbeError, OSError) as e:
        logger.debug("Failed to set mute state: %s", e)
        return False
