"""Adjust the Pi's speaker volume.

Used to let the caller nudge the volume up/down by typing +/- (or plus/moins)
in the Jitsi chat — she can't reach the Pi's controls, and it's easier than
switching back to the family app mid-call.
"""

import logging
import subprocess

logger = logging.getLogger("visio-tv.audio")

DEFAULT_SINK = "@DEFAULT_AUDIO_SINK@"
MAX_VOLUME = "1.0"  # cap so a burst of "+" can't push it into distortion


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
