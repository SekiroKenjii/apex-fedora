"""Boot a stopped test run again over the same overlays and the same firmware variables.

A run that was stopped, or crashed on purpose, is resumed as the machine it was, from the
record it left: the overlays are not remade, the variables the machine wrote are kept and
a copy of them and of the serial log is stamped aside first so the earlier boot's evidence
survives the next. A run that carried the emulated usb bus is not resumed, because the
fixture that was hot-plugged into it cannot be attached again the same way; and the image
it booted from may be left out, which is how an installed disk is booted after its install.
"""

from __future__ import annotations

from pathlib import Path

from apex.config import defaults, loader
from apex.kernel import errors, identifiers, refusals, safepaths
from apex.ports import portset
from apex.provisioning import launching, runrecord, testspec


def resume(
    ports: portset.HostPorts,
    settings: loader.Settings,
    root: safepaths.RuntimeRoot,
    run: identifiers.RunId,
    *,
    stamp: identifiers.Token,
    without_iso: bool,
) -> testspec.Prepared:
    run_directory = root.child(f"{defaults.RUNS_DIRECTORY}/{run}")
    record = runrecord.read(ports, run_directory)
    if record.usb_bus or record.boot_usb is not None:
        raise errors.Refusal(
            refusals.RefusalReason.TOPOLOGY_INCONSISTENT,
            subject="a run with the emulated usb bus",
            remedy="start a fresh usb test; resuming would change its hotplug topology",
        )
    if launching.current(ports, root=root) is not None:
        raise errors.Refusal(
            refusals.RefusalReason.MACHINE_RUNNING,
            subject="a machine is running",
            remedy="stop it before resuming a run",
        )
    _preserve(ports, run_directory, stamp)

    def present(path: Path) -> safepaths.SafePath:
        return safepaths.SafePath.regular_file(path, within=root)

    iso = None if without_iso else record.iso
    variables = safepaths.SafePath(run_directory.path / defaults.VARIABLES_NAME)
    if not ports.files.exists(variables):
        raise errors.Refusal(
            refusals.RefusalReason.PATH_NOT_A_REGULAR_FILE,
            subject=f"{variables}: the run left no firmware variables to boot with",
        )
    spec = testspec.describe(
        settings,
        root,
        run_directory,
        disk=present(record.disk.overlay),
        extras=tuple(present(item.overlay) for item in record.extras),
        variables=variables,
        iso=iso,
        guest_ssh=record.guest_ssh,
        serial_console=record.serial_console,
        usb_bus=False,
        boot_usb=None,
    )
    return testspec.Prepared(
        run=run,
        run_directory=run_directory,
        spec=spec,
        medium=None if iso is None else record.medium,
    )


def _preserve(
    ports: portset.HostPorts, run_directory: safepaths.SafePath, stamp: identifiers.Token
) -> None:
    """The variables and the serial log as the earlier boot left them, stamped aside."""
    for name, kept in (
        (defaults.VARIABLES_NAME, f"{defaults.RESUME_PREFIX}{stamp}-vars.fd"),
        (defaults.TEST_SERIAL_LOG_NAME, f"{defaults.RESUME_PREFIX}{stamp}-serial.log"),
        (defaults.RUN_RECORD_NAME, f"{defaults.RESUME_PREFIX}{stamp}.json"),
    ):
        source = safepaths.SafePath(run_directory.path / name)
        if ports.files.exists(source):
            ports.files.copy(source, safepaths.SafePath(run_directory.path / kept))
