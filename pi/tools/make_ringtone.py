#!/usr/bin/env python3
"""Generate the doorbell-style chime the Pi plays when a call starts.

Kept as a generator rather than a committed audio file: no binary blob in git,
no licensing question, and the tone is easy to tweak (pitch, warmth, volume).

A descending major third is used — the classic doorbell interval, immediately
recognisable and gentle enough for an elderly person, unlike a harsh buzzer.

Usage: python3 make_ringtone.py [output.wav]
"""

import math
import struct
import sys
import wave

SAMPLE_RATE = 44100
PATTERN_SECONDS = 3.0  # chime, then silence; the listener loops this
AMPLITUDE = 0.38  # leaves headroom so it never clips or sounds harsh

# (frequency Hz, start time s, duration s) — E5 then C5
NOTES = ((659.25, 0.00, 0.55), (523.25, 0.45, 1.10))


def _note_sample(freq: float, t: float, duration: float) -> float:
    """One bell-ish sample: fast attack, exponential decay, soft harmonic."""
    if t < 0 or t > duration:
        return 0.0
    attack = min(1.0, t / 0.012)  # avoids a click at note onset
    decay = math.exp(-3.2 * t / duration)
    fundamental = math.sin(2 * math.pi * freq * t)
    harmonic = 0.28 * math.sin(2 * math.pi * freq * 2 * t)  # warmth
    return attack * decay * (fundamental + harmonic) / 1.28


def build() -> bytes:
    frames = bytearray()
    total = int(SAMPLE_RATE * PATTERN_SECONDS)
    for i in range(total):
        t = i / SAMPLE_RATE
        value = sum(_note_sample(f, t - start, dur) for f, start, dur in NOTES)
        sample = int(max(-1.0, min(1.0, value * AMPLITUDE)) * 32767)
        frames += struct.pack("<h", sample)
    return bytes(frames)


def main() -> None:
    out = sys.argv[1] if len(sys.argv) > 1 else "ringtone.wav"
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(build())
    print(f"Wrote {out} ({PATTERN_SECONDS}s pattern)")


if __name__ == "__main__":
    main()
