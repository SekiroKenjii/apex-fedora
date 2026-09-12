"""The one place a number lives.

A timeout, a port, a size or a budget is declared here and read through `Settings`. A value
that is observed from an image or derived from a release profile does not belong here.
"""

from __future__ import annotations

import dataclasses

from apex.kernel import bounded, quantities, safepaths, timing

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
FINGERPRINT_TESTS_DIRECTORY = "fingerprint-tests"
FINGERPRINT_SOURCES_NAME = "fingerprint-sources"
FINGERPRINT_LOCK_DIRECTORY = "config"
FINGERPRINT_LOCK_NAME = "fingerprint-tests.lock.json"
FINGERPRINT_OUTPUT_DIRECTORY = "output/fingerprint"
FINGERPRINT_PACKAGES = ("fprintd", "libfprint")
FINGERPRINT_TEST_PACKAGES = ("python3-dbusmock", "python3-gobject", "python3-cairo", "dbus-daemon")
FINGERPRINT_TEST_DEADLINE = timing.Deadline(timing.Elapsed(180))
RPM_NEVRA_FORMAT = "%{NAME}-%{VERSION}-%{RELEASE}.%{ARCH}\\n"
RPM_EVRA_FORMAT = "%{NAME}-%{EVR}.%{ARCH}\\n"
RECORD_MODE = quantities.FileMode(0o600)

DOCUMENT_LIMIT = bounded.Limit(4 * 1024 * 1024)
PROBE_DEADLINE = timing.Deadline(timing.Elapsed(20))
OBSERVATION_DEADLINE = timing.Deadline(timing.Elapsed(15))
OBSERVATION_LIMIT = bounded.CAPTURE_LIMIT
LIVE_ROOT_TOKEN = "root=live:CDLABEL=Apex-Live"
SETTLE_DEADLINE = timing.Deadline(timing.Elapsed(25))
INITRD_RELEASE = "/etc/initrd-release"
MOUNTS = "/proc/mounts"
SYSROOT = "/sysroot"
PROTECTION_LATCH = "/run/apex-protection-failed"
LIVE_GUARD = "/usr/libexec/apex/live-disk-guard.sh"
OSTREE_BOOTED = "/run/ostree-booted"
INSTALLER_MARKER = "/usr/share/apex/installer-payload.json"
BOOT_ID = "/proc/sys/kernel/random/boot_id"
LOG_LIMIT = bounded.Limit(2 * 1024 * 1024)
LOG_ERROR_LIMIT = 4096
INSTALLER_QUERY_DEADLINE = timing.Deadline(timing.Elapsed(5))
ANACONDA_DEADLINE = timing.Deadline(timing.Elapsed(35))
INSTALLER_PAYLOAD = "/usr/share/apex/payload"
INSTALLER_TRUST = "/usr/share/apex/installer-trust"
INSTALLER_PREFLIGHT_RECORD = "/run/apex/installer-preflight.json"
INSTALLER_FAULT_DIRECTORY = "/run/apex-installer-fault"
CONTAINER_POLICY = "/etc/containers/policy.json"
ANACONDA_LOG = "/tmp/anaconda.log"
SIGNING_DEADLINE = timing.Deadline(timing.Elapsed(60))
DOWNLOAD_DEADLINE = timing.Deadline(timing.Elapsed(1200))
DOWNLOAD_CONNECT_TIMEOUT = timing.Elapsed(20)
DOWNLOAD_RETRIES = 2
SSH_CONNECT_TIMEOUT = timing.Elapsed(5)
GUEST_COMMAND_DEADLINE = timing.Deadline(timing.Elapsed(300))
TRANSFER_DEADLINE = timing.Deadline(timing.Elapsed(1800))
BUILD_DEADLINE = timing.Deadline(timing.Elapsed(4 * 3600))
ENGINE_QUERY_DEADLINE = timing.Deadline(timing.Elapsed(120))
ENGINE_BUILD_DEADLINE = timing.Deadline(timing.Elapsed(3600))
BUILDER_USER = "builder"
BUILDER_OWNER = "builder:builder"
BUILDER_KEY_NAME = "builder_ed25519"
KNOWN_HOSTS_NAME = "known_hosts"
BUILDER_MARKER = "/etc/apex-builder"
BUILDER_MARKER_TEXT = "apex-isolated-builder-v1"
VIRTUALISERS = frozenset({"kvm", "qemu"})
PARTITION_APPEARS = timing.WaitPolicy(
    deadline=timing.Deadline(timing.Elapsed(5)),
    backoff=timing.Backoff.exponential(
        first=timing.Elapsed(0.1), ceiling=timing.Elapsed(0.1), factor=1
    ),
    description="the partition node appears",
)
PACKAGE_INSTALL_DEADLINE = timing.Deadline(timing.Elapsed(1800))
BUILD_LOCK = safepaths.RemotePath("/run/apex-build.lock")
REMOTE_PREFIX = "/var/tmp/apex-"
REMOTE_DIRECTORY_MODE = "700"
AGENT_DIRECTORY = "agent"
AGENT_WHEEL_NAME = "apex-agent.whl"
AGENT_LIBRARY = "lib"
AGENT_REPLY_LIMIT = bounded.Limit(32 * 1024 * 1024)
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
