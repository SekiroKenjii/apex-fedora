"""An installer test run as the payload fault and its collection expect to find it.

The run record says the machine booted the installer image over a serial console with one
extra disk; the guest's report is the one the production guard leaves when it refuses the
payload before Anaconda; the installer logs are three whole files.
"""

from __future__ import annotations

import base64
import hashlib
from collections.abc import Mapping
from pathlib import Path

from apex.kernel import identifiers, safepaths
from apex.model import machines
from apex.ports import portset
from apex.provisioning import runrecord

ISO_NAME = "installer.iso"
ISO_BYTES = b"the signed installer image"
CASE = "corrupt-blob"


def confirming(case: str = CASE) -> dict[str, object]:
    """A report the host confirms: the case, refused before Anaconda, nothing touched."""
    return {
        "case": case,
        "status": "PASS",
        "returncode": 1,
        "preflight": {"status": "FAIL", "reason": "Bundled blob checksum mismatch"},
        "upstream_log_created": False,
        "selinux_after": "Enforcing",
    }


def whole_log(data: bytes) -> dict[str, object]:
    return {
        "data": base64.b64encode(data).decode(),
        "sha256": hashlib.sha256(data).hexdigest(),
        "truncated": False,
    }


def diagnostics(**overrides: Mapping[str, object]) -> dict[str, object]:
    logs: dict[str, object] = {
        name: whole_log(f"{name} contents\n".encode())
        for name in ("anaconda.log", "storage.log", "program.log")
    }
    logs.update(overrides)
    return {"schema": 1, "payload": {}, "boot_id": "b" * 32, "logs": logs, "observations": {}}


def record(
    ports: portset.HostPorts,
    root: safepaths.RuntimeRoot,
    run_directory: safepaths.SafePath,
    *,
    medium: machines.Medium | None = machines.Medium.INSTALLER,
    serial_console: bool = True,
    extras: int = 1,
) -> Path:
    """The run's record written through the ports, and the image it names on the disk."""
    iso = root.path / ISO_NAME
    iso.write_bytes(ISO_BYTES)
    layer = runrecord.Layer(
        source=root.path / "disk.qcow2", overlay=run_directory.path / "disk.qcow2"
    )
    runrecord.write(
        ports,
        run_directory,
        runrecord.RunRecord(
            run=identifiers.RunId.parse(run_directory.path.name),
            disk=layer,
            extras=tuple(
                runrecord.Layer(
                    source=root.path / f"other-{index}.qcow2",
                    overlay=run_directory.path / f"other-{index}.qcow2",
                )
                for index in range(1, extras + 1)
            ),
            iso=iso,
            medium=medium,
            guest_ssh=False,
            serial_console=serial_console,
            usb_bus=False,
            boot_usb=None,
        ),
    )
    return iso
