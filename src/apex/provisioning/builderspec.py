"""The builder machine as the settings and the runtime root describe it.

Every file the machine attaches must already be there: the disk, the seed and the firmware
variables under the runtime root, the firmware code where the host settings say. Nothing
here creates or downloads; preparing that storage is another operation.
"""

from __future__ import annotations

from apex.config import defaults, loader
from apex.kernel import safepaths
from apex.model import machines


def spec(settings: loader.Settings, root: safepaths.RuntimeRoot) -> machines.VmSpec:
    code = safepaths.RegularFile.adopt(settings.builder.firmware_code)
    return machines.VmSpec.build(
        role=machines.VmRole.BUILDER,
        resources=machines.VmResources(
            memory=settings.builder.memory, processors=settings.builder.processors
        ),
        root_disk=safepaths.SafePath.regular_file(
            root.path / defaults.BUILDER_DISK_NAME, within=root
        ),
        firmware=machines.Firmware(
            code=safepaths.SafePath(code.path),
            variables=safepaths.SafePath.regular_file(
                root.path / defaults.BUILDER_VARIABLES_NAME, within=root
            ),
        ),
        monitor=machines.MonitorSocket(root.child(defaults.MONITOR_SOCKET_NAME)),
        serial=machines.SerialFile(root.child(defaults.BUILDER_SERIAL_LOG_NAME)),
        seed=safepaths.SafePath.regular_file(root.path / defaults.BUILDER_SEED_NAME, within=root),
        network=machines.RestrictedNet(
            forwarded_port=defaults.BUILDER.ssh_port, role=machines.VmRole.BUILDER
        ),
    )
