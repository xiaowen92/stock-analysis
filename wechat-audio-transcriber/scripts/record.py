"""Record system audio via BlackHole — auto-switch audio output, no manual steps.

Usage:
    python3 scripts/record.py                        # Listen + Record, Ctrl+C to stop
    python3 scripts/record.py -q                      # Record only (silent)
    python3 scripts/record.py -q -d 600               # Silent, 10 min auto-stop
    python3 scripts/record.py -o course.flac          # Custom output path

Dependencies: sounddevice, numpy, soundfile, SwitchAudioSource (brew install switchaudio-osx)
Prerequisite: Audio MIDI Setup → Multi-Output Device (Speakers + BlackHole 2ch)
"""

import sys
import os
import subprocess
import datetime
from pathlib import Path

import sounddevice as sd
import numpy as np
import soundfile as sf

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SAMPLE_RATE = 48000
BLACKHOLE_NAME = "BlackHole 2ch"
SWITCH = "SwitchAudioSource"

# ---------------------------------------------------------------------------
# Helpers: audio device switching
# ---------------------------------------------------------------------------

def _switch_output(device: str):
    subprocess.run([SWITCH, "-s", device], check=True, capture_output=True)

def _current_output() -> str:
    return subprocess.run([SWITCH, "-c"], check=True, capture_output=True, text=True).stdout.strip()

def _list_outputs() -> list[str]:
    result = subprocess.run([SWITCH, "-a", "-t", "output"], check=True, capture_output=True, text=True)
    return [line for line in result.stdout.strip().split("\n") if line]

def _find_multi_output() -> str | None:
    """Find Multi-Output Device containing BlackHole."""
    for dev in _list_outputs():
        lower = dev.lower()
        if "blackhole" in lower and dev != BLACKHOLE_NAME:
            return dev
        if "multi" in lower and "output" in lower:
            return dev
    return None

def _find_blackhole_device() -> tuple[int, dict]:
    """Find BlackHole input device index and info."""
    devices = sd.query_devices()
    for i, dev in enumerate(devices):
        if BLACKHOLE_NAME in dev["name"]:
            return i, dev
    print(f"[ERROR] Device not found: {BLACKHOLE_NAME}")
    print("Available devices:")
    for i, dev in enumerate(devices):
        print(f"  {i}: {dev['name']} (in={dev['max_input_channels']}, out={dev['max_output_channels']})")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Record
# ---------------------------------------------------------------------------

def _record_continuous(dev_idx: int, channels: int) -> np.ndarray:
    """Record until Ctrl+C, return captured audio."""
    chunks = []
    chunk_size = SAMPLE_RATE

    def callback(indata, frames, time, status):
        if status:
            print(f"[WARNING] {status}", file=sys.stderr)
        chunks.append(indata.copy())

    try:
        with sd.InputStream(
            samplerate=SAMPLE_RATE, channels=channels, device=dev_idx,
            dtype="float32", callback=callback, blocksize=chunk_size,
        ):
            while True:
                sd.sleep(100)
    except KeyboardInterrupt:
        pass

    return np.concatenate(chunks, axis=0)


def _record_fixed(dev_idx: int, channels: int, duration: float) -> np.ndarray:
    """Record for fixed duration, return audio array."""
    frames = int(duration * SAMPLE_RATE)
    audio = sd.rec(
        frames=frames, samplerate=SAMPLE_RATE, channels=channels,
        device=dev_idx, dtype="float32",
    )
    sd.wait()
    return audio

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    # --- Parse args ---
    quiet = False
    duration = None
    output = None

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "-q":
            quiet = True; i += 1
        elif args[i] == "-d" and i + 1 < len(args):
            duration = float(args[i + 1]); i += 2
        elif args[i] == "-o" and i + 1 < len(args):
            output = args[i + 1]; i += 2
        elif args[i] == "-h":
            print(__doc__); sys.exit(0)
        else:
            print(f"Unknown arg: {args[i]}")
            print(__doc__); sys.exit(1)

    # --- Determine output device ---
    if quiet:
        target_output = BLACKHOLE_NAME
        mode_desc = "Record only (silent)"
    else:
        multi = _find_multi_output()
        if multi is None:
            print("[ERROR] Multi-Output Device not found. Create one in Audio MIDI Setup,")
            print("or use -q for silent recording.")
            sys.exit(1)
        target_output = multi
        mode_desc = "Listen + Record"

    # --- Output file ---
    if output is None:
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        output = f"record_{ts}.flac"

    # --- Save original output & set up restore ---
    original_output = _current_output()

    def cleanup():
        if _current_output() != original_output:
            print(f"\nRestoring output: {original_output}")
            _switch_output(original_output)

    try:
        # --- Switch ---
        if original_output != target_output:
            print(f"Output: {original_output} -> {target_output}")
            _switch_output(target_output)
        else:
            print(f"Output: {target_output} (already set)")

        # --- Record ---
        dev_idx, dev_info = _find_blackhole_device()
        channels = min(dev_info["max_input_channels"], 2)

        print(f"Mode:   {mode_desc}")
        print(f"Device: {BLACKHOLE_NAME} (ch={channels}, {SAMPLE_RATE}Hz)")
        print(f"Output: {output}")
        if duration:
            print(f"Length: {duration}s")
            print("Recording...")
            audio = _record_fixed(dev_idx, channels, duration)
        else:
            print("Recording until Ctrl+C...")
            audio = _record_continuous(dev_idx, channels)
            if len(audio) == 0:
                print("[ERROR] No audio captured")
                sys.exit(1)

        # --- Save ---
        sf.write(output, audio, SAMPLE_RATE, format="FLAC", subtype="PCM_24")
        print(f"\n[Done] {output}")
        print(f"Recorded {len(audio) / SAMPLE_RATE:.1f}s")

    finally:
        cleanup()


if __name__ == "__main__":
    main()
