"""The one place a number lives.

A timeout, a port, a size or a budget is declared here and read through `Settings`. A value
that is observed from an image or derived from a release profile does not belong here.
"""

from __future__ import annotations

import dataclasses

from apex.kernel import bounded, quantities, timing

BUILDER_SSH_PORT = quantities.TcpPort(22244)
GUEST_SSH_PORT = quantities.TcpPort(22245)

CAPTURE_LIMIT = bounded.CAPTURE_LIMIT
SERIAL_CHUNK = bounded.SERIAL_CHUNK

SOURCE_PATHS = ("Containerfile", "config", "guest", "rpms", "system_files", "live", "tools")
EXPORT_DIRECTORY = "exports"
SOURCE_ARCHIVE_NAME = "source.tar"
SOURCE_MANIFEST_NAME = "source-manifest.json"
SOURCES_DIRECTORY = "sources"
LOCK_COPY_NAME = "sources.lock.json"
RECORD_MODE = quantities.FileMode(0o600)

DOCUMENT_LIMIT = bounded.Limit(4 * 1024 * 1024)
PROBE_DEADLINE = timing.Deadline(timing.Elapsed(20))
SIGNING_DEADLINE = timing.Deadline(timing.Elapsed(60))
DOWNLOAD_DEADLINE = timing.Deadline(timing.Elapsed(1200))
DOWNLOAD_CONNECT_TIMEOUT = timing.Elapsed(20)
DOWNLOAD_RETRIES = 2
IMAGE_TOOL_DEADLINE = timing.Deadline(timing.Elapsed(120))
MACHINE_LOCK = "machine"
INTENT_NAME = "machine-intent.json"
LEASE_NAME = "machine.json"
RUNS_DIRECTORY = "vm-runs"
MONITOR_SOCKET_NAME = "qmp.sock"
SERIAL_SOCKET_NAME = "serial.sock"
HYPERVISOR_LOG_NAME = "qemu.log"
INITIAL_VARIABLES_NAME = "initial-vars.fd"
VARIABLES_NAME = "test-vars.fd"
POWER_LOSS_RECORD = "power-loss.json"
COMPARISON_RECORD = "disk-comparison.json"
FIRMWARE_VARIABLES_LIMIT = bounded.Limit(8 * 1024 * 1024)
TEST_MACHINE_MINIMUM_FREE = quantities.Gib(12)
MONITOR_APPEARS = timing.Deadline(timing.Elapsed(10))
MONITOR_POLL = timing.Elapsed(0.05)
REAP_DEADLINE = timing.Deadline(timing.Elapsed(5))
QMP_DEADLINE = timing.Deadline(timing.Elapsed(10))
QMP_LINE_LIMIT = bounded.Limit(1024 * 1024)


@dataclasses.dataclass(frozen=True, slots=True)
class BuilderDefaults:
    processors: int
    memory: quantities.Mib
    reserve: quantities.Mib
    disk: quantities.Gib
    minimum_free: quantities.Gib
    ssh_port: quantities.TcpPort


BUILDER = BuilderDefaults(
    processors=4,
    memory=quantities.Mib(6144),
    reserve=quantities.Mib(1536),
    disk=quantities.Gib(160),
    minimum_free=quantities.Gib(180),
    ssh_port=BUILDER_SSH_PORT,
)


@dataclasses.dataclass(frozen=True, slots=True)
class TestMachineDefaults:
    processors: int
    memory: quantities.Mib
    ssh_port: quantities.TcpPort


TEST_MACHINE = TestMachineDefaults(
    processors=4,
    memory=quantities.Mib(4096),
    ssh_port=GUEST_SSH_PORT,
)

BOOT_READY = timing.WaitPolicy(
    deadline=timing.Deadline(timing.Elapsed(240)),
    backoff=timing.Backoff.exponential(
        first=timing.Elapsed(0.05), ceiling=timing.Elapsed(2), factor=2
    ),
    description="the guest answers on its monitor socket",
)

SHUTDOWN = timing.WaitPolicy(
    deadline=timing.Deadline(timing.Elapsed(45)),
    backoff=timing.Backoff.exponential(
        first=timing.Elapsed(0.1), ceiling=timing.Elapsed(2), factor=2
    ),
    description="the guest process exits",
)

# Entry, content and message rules shipped so far. A registry that loads fewer permits whatever
# the missing rules would have refused, and says nothing about it, which is the one failure of
# a guard that looks exactly like success.
REPOSITORY_RULE_FLOOR = (13, 6, 5)
