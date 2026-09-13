"""Dispatch subcommands that still live in the pre-restructure tools tree.

Every migration phase moves commands out of this allowlist into their own unit. The list
only ever shrinks, which `tests/architecture/test_legacy_bridge.py` enforces against the
previous commit, so the interim state cannot quietly become permanent. A name whose work
moved to a command spelt differently is retired: it names its replacement and is refused,
so habit is corrected at the prompt rather than answered by the older tree.
"""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[3]
LEGACY_TOOLS = REPOSITORY / "tools"
LEGACY_ENTRY_POINT = LEGACY_TOOLS / "apex.py"

BRIDGED: frozenset[str] = frozenset()
RETIRED: dict[str, str] = {
    "artifact": "apex build qcow2|installer|live --parent <id> [--test-access]",
    "builder": "apex machine prepare, start --role builder, stop, status",
    "report": "apex readiness",
    "select-candidate": "apex candidate select --build <id> --key <public key>",
    "test-artifact": "apex trust exercise --build <id> --key <public key>",
    "trust-development-key": "apex trust development-key",
    "verify-artifact": "apex trust verify --build <id> --key <public key>",
    "test-vm": "apex machine start --role test --disk <qcow2> [--iso --medium --extra-disk "
               "--guest-ssh --serial-console --usb-bus --boot-usb]",
    "test-hotplug-usb": "apex machine hotplug-usb --source <qcow2>",
    "test-power-loss": "apex machine power-loss",
    "test-fingerprint": "apex verify fingerprint-cleanup --build <id>",
    "test-installer-trust": "apex verify installer-trust",
    "test-compare-disks": "apex machine compare --run <id or run directory>",
    "test-resume": "apex machine resume --run <id or run directory> [--without-iso]",
    "test-live-check": "apex verify <case> --serial",
    "test-installer-fault": (
        "apex verify installer-payload --case <case> [--wrong-key <public key>] --serial"
    ),
    "test-installer-fault-collect": "apex machine collect --run <id or run directory>",
    "installer-logs": "apex verify installer-diagnostics --serial",
    "installer-fixtures": "apex build fixtures",
    "hardware-snapshot": "apex hardware snapshot",
    "build-nvidia": "apex build nvidia --parent <id>",
    "decode-coefficient": "apex hardware decode-coefficient <nid> <verb> <parameter>",
}


def handles(command: str) -> bool:
    return command in BRIDGED


def replacement(command: str) -> str | None:
    """What a retired name is now spelt as, or nothing for a name that is not retired."""
    return RETIRED.get(command)


def dispatch(arguments: list[str]) -> int:
    """Run the legacy entry point in this interpreter and return its exit code."""
    if str(LEGACY_TOOLS) not in sys.path:
        sys.path.insert(0, str(LEGACY_TOOLS))
    original = sys.argv
    sys.argv = [str(LEGACY_ENTRY_POINT), *arguments]
    try:
        runpy.run_path(str(LEGACY_ENTRY_POINT), run_name="__main__")
    except SystemExit as exit_request:
        return int(exit_request.code or 0)
    finally:
        sys.argv = original
    return 0
