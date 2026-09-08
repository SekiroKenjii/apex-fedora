#!/usr/bin/python3
"""Collect read-only diagnostics. Output stays on operator-selected storage."""
import argparse
import json
import os
from pathlib import Path
import subprocess
from datetime import datetime, timezone


def collect():
    commands = {
        "kernel": ["uname", "-r"],
        "packages": ["rpm", "-q", "kernel-core", "libfprint", "fprintd", "alsa-ucm", "pipewire", "wireplumber"],
        "audio": ["wpctl", "status"],
        "mixer": ["amixer", "scontents"],
        "fprint_journal": ["journalctl", "-b", "-u", "fprintd", "--no-pager", "-n", "120"],
        "sessions": ["loginctl", "list-sessions", "--no-legend"],
    }
    result = {"timestamp": datetime.now(timezone.utc).isoformat(), "status": "OBSERVATION", "commands": {}, "codecs": {}}
    for name, args in commands.items():
        try:
            proc = subprocess.run(args, capture_output=True, text=True, timeout=20)
            result["commands"][name] = {"returncode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}
        except (OSError, subprocess.TimeoutExpired) as exc:
            result["commands"][name] = {"error": str(exc)}
    for codec in Path("/proc/asound").glob("card*/codec#*"):
        result["codecs"][str(codec)] = codec.read_text()
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    # Exclusive creation protects an earlier diagnostic capture.
    fd = os.open(args.destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(collect(), f, indent=2)
        f.write("\n")
