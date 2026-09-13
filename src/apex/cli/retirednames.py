"""The names the older tree answered for that the new tree spells differently.

A retired name is refused with its replacement written out, so habit is corrected at the
prompt; the names that moved under their own spelling need no entry, and the older entry
point that once answered for everything else is gone.
"""

from __future__ import annotations

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
    "decode-coefficient": "apex hardware decode-coefficient <nid> <verb> <parameter>",
    "build-nvidia": "apex build nvidia --parent <id>",
}


def replacement(command: str) -> str | None:
    """What a retired name is now spelt as, or nothing for a name that is not retired."""
    return RETIRED.get(command)
