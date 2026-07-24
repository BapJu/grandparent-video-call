"""Adjust the Pi's speaker volume.

Used to let the caller nudge the volume up/down from the call view, since she
can't reach the Pi's controls.
"""

import logging
import os
import subprocess

logger = logging.getLogger("visio-tv.audio")

DEFAULT_SINK = "@DEFAULT_AUDIO_SINK@"
# Allow software boost past 100% — a small speaker on the HDMI→VGA jack can be
# quiet, so headroom matters more than the slight distortion risk near the top.
MAX_VOLUME = os.environ.get("MAX_VOLUME", "1.5")


def nudge(step_percent: int) -> None:
    """Raise (positive) or lower (negative) the default sink volume."""
    direction = "+" if step_percent >= 0 else "-"
    arg = f"{abs(step_percent)}%{direction}"
    try:
        # -l caps the ceiling; only meaningful when raising, harmless otherwise.
        subprocess.run(
            ["wpctl", "set-volume", "-l", MAX_VOLUME, DEFAULT_SINK, arg],
            check=False,
            timeout=5,
        )
        logger.info("Volume %s%d%%", direction, abs(step_percent))
    except (FileNotFoundError, subprocess.SubprocessError) as e:
        logger.warning("Failed to change volume: %s", e)
