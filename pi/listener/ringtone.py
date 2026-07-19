"""Play the "come to the screen" chime when a call starts.

There is no "answer" action on the Pi — nobody presses anything — so the
ringtone can't stop on being answered. It simply rings for a fixed time, like
a phone that gives up, and is cancelled early if the call ends.

Played through PipeWire (pw-play), independently of the call audio: the
mixer handles both at once.
"""

import asyncio
import logging
import os
import shutil

logger = logging.getLogger("visio-tv.ringtone")

_PLAYERS = ("pw-play", "paplay", "aplay")


def find_player() -> str | None:
    for name in _PLAYERS:
        if shutil.which(name):
            return name
    return None


async def ring(path: str, duration: float) -> None:
    """Loop the chime for `duration` seconds. Cancel the task to stop early."""
    if not os.path.isfile(path):
        logger.warning("Ringtone file missing: %s", path)
        return
    player = find_player()
    if player is None:
        logger.warning("No audio player found (pw-play/paplay/aplay) — no ringtone")
        return

    loop = asyncio.get_running_loop()
    deadline = loop.time() + duration
    logger.info("Ringing for %ss via %s", int(duration), player)
    proc = None
    try:
        while loop.time() < deadline:
            proc = await asyncio.create_subprocess_exec(
                player,
                path,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()
            proc = None
    except asyncio.CancelledError:
        if proc is not None and proc.returncode is None:
            proc.kill()
        logger.info("Ringtone stopped early")
        raise
    finally:
        logger.debug("Ringtone finished")
