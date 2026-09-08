#!/usr/bin/python3
"""Report guest state without declaring visual or hardware tests passed."""
import json
import subprocess


def check(args):
    proc = subprocess.run(args, capture_output=True, text=True, timeout=20)
    return {"returncode": proc.returncode, "stdout": proc.stdout.strip(), "stderr": proc.stderr.strip()}


result = {name: check(command) for name, command in {
    "bootc": ["bootc", "status", "--format", "json"],
    "gdm": ["systemctl", "is-active", "gdm"],
    "dbus": ["busctl", "--system", "call", "org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "GetId"],
    "root_mount": ["findmnt", "--noheadings", "--output", "TARGET,SOURCE,FSTYPE,OPTIONS", "/"],
    "failed_units": ["systemctl", "--failed", "--no-legend"],
    "sessions": ["loginctl", "list-sessions", "--no-legend"],
    "selinux": ["getenforce"],
    "kernel": ["uname", "-r"],
}.items()}
print(json.dumps({"observations": result, "visual_test": "NOT TESTED"}, indent=2))
