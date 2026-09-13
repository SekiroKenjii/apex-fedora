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
RUNTIME_BASE = "~/.local/share/apex-fedora"
HOST_SETTINGS_FILE = "~/.config/apex-fedora/settings.toml"

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
WINDOW_APPEARS = timing.WaitPolicy(
    deadline=timing.Deadline(timing.Elapsed(30)),
    backoff=timing.Backoff.exponential(
        first=timing.Elapsed(1), ceiling=timing.Elapsed(1), factor=1
    ),
    description="the probe's window is presented",
)
SHELL_THEME_SOURCE = "/usr/share/apex/shell-theme-source.json"
WINDOW_SETTLE = timing.Elapsed(3)
SHELL_SETTLE = timing.Elapsed(2)
BARS_APPEAR = timing.WaitPolicy(
    deadline=timing.Deadline(timing.Elapsed(45)),
    backoff=timing.Backoff.exponential(
        first=timing.Elapsed(1), ceiling=timing.Elapsed(1), factor=1
    ),
    description="the render probe's bars are visible",
)
ESCAPE_KEY = "esc"
RETURN_KEY = "ret"
OVERVIEW_KEY = "meta_l"
KEY_INTERVAL = timing.Elapsed(0.1)
GREETER_SETTLE = timing.Elapsed(3)
PROMPT_SETTLE = timing.Elapsed(1)
WELCOME_SETTLE = timing.Elapsed(1)
SEAT = "seat0"
GREETER_CLASS = "greeter"
WAYLAND_SESSION = "wayland"
SHELL_STARTED_MESSAGE = "f3ea493c22934e26811cd62abe8e203a"
TEST_ACCESS_DIRECTORY = "test-access"
TEST_ACCOUNT = "apex-test"
TEST_ACCOUNT_DESCRIPTION = "Disposable Apex VM test account"
TEST_KEY_NAME = "id_ed25519"
TEST_KEY_COMMENT = "apex-disposable-test"
TEST_BLUEPRINT_NAME = "blueprint.toml"
REMOTE_BLUEPRINT_NAME = "test-blueprint.toml"
TEST_KERNEL_APPEND = "systemd.wants=sshd.service"
PASSWORD_HASH_DEADLINE = timing.Deadline(timing.Elapsed(30))
CREDENTIALS_NAME = "credentials.json"
GREETER_APPEARS = timing.WaitPolicy(
    deadline=timing.Deadline(timing.Elapsed(60)),
    backoff=timing.Backoff.exponential(
        first=timing.Elapsed(1), ceiling=timing.Elapsed(1), factor=1
    ),
    description="GDM presents a greeter session on the seat",
)
SESSION_APPEARS = timing.WaitPolicy(
    deadline=timing.Deadline(timing.Elapsed(90)),
    backoff=timing.Backoff.exponential(
        first=timing.Elapsed(1), ceiling=timing.Elapsed(1), factor=1
    ),
    description="the account's Wayland session appears on the seat",
)
SHELL_STARTS = timing.WaitPolicy(
    deadline=timing.Deadline(timing.Elapsed(90)),
    backoff=timing.Backoff.exponential(
        first=timing.Elapsed(1), ceiling=timing.Elapsed(1), factor=1
    ),
    description="GNOME Shell reports its startup complete",
)
OVERVIEW_SETTLES = timing.WaitPolicy(
    deadline=timing.Deadline(timing.Elapsed(15)),
    backoff=timing.Backoff.exponential(
        first=timing.Elapsed(0.5), ceiling=timing.Elapsed(0.5), factor=1
    ),
    description="the Shell's Overview reaches the expected state",
)
SHELL_SHORTCUT = ("meta_l", "s")
SCREENS_DIRECTORY = "screens"
GTK_THEME_NAME = "Adwaita-dark"
SHELL_THEME_NAME = "Shadcn-Graphite"
GTK_THEME = f"'{GTK_THEME_NAME}'"
SHELL_THEME = f"'{SHELL_THEME_NAME}'"
WAYLAND_DISPLAY = "GdkWaylandDisplay"
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
SCREEN_LIMIT = bounded.Limit(64 * 1024 * 1024)
KEY_HOLD_MILLISECONDS = 40


@dataclasses.dataclass(frozen=True, slots=True)
class BuilderDefaults:
    processors: int
    memory: quantities.Mib
    reserve: quantities.Mib
    disk: quantities.Gib
    minimum_free: quantities.Gib
    ssh_port: quantities.TcpPort
    firmware_code: str
    firmware_variables: str


BUILDER = BuilderDefaults(
    processors=4,
    memory=quantities.Mib(6144),
    reserve=quantities.Mib(1536),
    disk=quantities.Gib(160),
    minimum_free=quantities.Gib(180),
    ssh_port=BUILDER_SSH_PORT,
    firmware_code="/usr/share/OVMF/OVMF_CODE_4M.fd",
    firmware_variables="/usr/share/OVMF/OVMF_VARS_4M.fd",
)
BUILDER_DISK_NAME = "builder.qcow2"
BUILDER_SEED_NAME = "seed.iso"
BUILDER_VARIABLES_NAME = "builder-vars.fd"
BUILDER_SERIAL_LOG_NAME = "builder-serial.log"
BUILDER_HOSTNAME = "apex-builder"
BUILDER_INSTANCE_PREFIX = "apex-builder-"
BUILDER_KEY_COMMENT = "apex-local-builder"
BUILDER_KEY_TYPE = "ed25519"
BUILDER_MARKER_MODE = "0600"
PUBLIC_KEY_SUFFIX = ".pub"
USER_DATA_NAME = "user-data"
META_DATA_NAME = "meta-data"
SEED_VOLUME = "cidata"
PACKAGEKIT_UNIT = "packagekit.service"
KEYGEN_DEADLINE = timing.Deadline(timing.Elapsed(60))
FINGERPRINT_WORK_PREFIX = "/var/tmp/apex-fingerprint-"
PAYLOAD_TAG_PREFIX = "localhost/apex-payload:"
PAYLOAD_MANIFEST_NAME = "payload-manifest.json"
TEST_DISK_NAME = "disk.qcow2"
TEST_EXTRA_DISK_PREFIX = "other-"
TEST_SERIAL_LOG_NAME = "test-serial.log"
TEST_BOOT_USB_NAME = "boot-usb.qcow2"
HOTPLUG_OVERLAY_NAME = "hotplug-usb.qcow2"
HOTPLUG_RECORD = "hotplug-request.json"
RUN_RECORD_NAME = "run.json"
SERIAL_LOCK_NAME = "serial-console.lock"
SERIAL_CONNECT_TIMEOUT = timing.Elapsed(5)
SERIAL_HANDSHAKE_DEADLINE = timing.Deadline(timing.Elapsed(45))
SERIAL_TRANSFER_LIMIT = bounded.Limit(16 * 1024 * 1024)
FAULT_REQUEST_NAME = "fault-request.json"
FAULT_GUEST_NAME = "fault-guest.json"
FAULT_RESULT_NAME = "fault-result.json"
PUBLIC_KEY_LIMIT = bounded.Limit(4096)
RESUME_PREFIX = "before-resume-"
TRUST_WORK_PREFIX = "/var/tmp/apex-trust-"
DEVELOPMENT_KEY_PATH = "/var/lib/apex/signing/local-dev.key"
TRUST_DIRECTORY = "trust"
DEVELOPMENT_KEY_NAME = "development.pub"
DEVELOPMENT_RECORD_NAME = "development.json"
DEVELOPMENT_PURPOSE = "local-development-only"
DEVELOPMENT_SOURCE = "authenticated builder ssh; not the artifact bundle"
SIGNATURE_TESTS_DIRECTORY = "signature-tests"
RESULTS_NAME = "results.json"
CANDIDATE_HISTORY_DIRECTORY = "candidate-history"
OPERATOR_NOTE_KIND = ".json"
PROOF_LIMIT = bounded.Limit(64 * 1024 * 1024)
KEY_CHECK_DEADLINE = timing.Deadline(timing.Elapsed(30))
GUEST_KEY_NAME = "guest_ed25519"
MAXIMUM_TEST_EXTRA_DISKS = 2


@dataclasses.dataclass(frozen=True, slots=True)
class TestMachineDefaults:
    processors: int
    memory: quantities.Mib
    ssh_port: quantities.TcpPort


TEST_MACHINE = TestMachineDefaults(
    processors=4, memory=quantities.Mib(4096), ssh_port=GUEST_SSH_PORT
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
SOURCE_BLOB_LIMIT = quantities.ByteCount(20 * 1024 * 1024)
HOOK_GIT_DEADLINE = timing.Deadline(timing.Elapsed(120))
HOOK_CONTENT_LIMIT = bounded.Limit(64 * 1024 * 1024)
HOOK_MARKER = "# apex-local-hook"
HOOK_MODE = quantities.FileMode(0o755)
HOST_TOOLS = ("python3", "qemu-system-x86_64", "qemu-img", "ssh", "ssh-keygen", "curl", "uv")
HARDWARE_OBSERVATIONS_DIRECTORY = "hardware-observations"
OBSERVATIONS_NAME = "observations.json"
SNAPSHOT_READ_LIMIT = bounded.Limit(256 * 1024)
SNAPSHOT_COMMAND_DEADLINE = timing.Deadline(timing.Elapsed(15))
NVIDIA_LOCK_PATH = "config/nvidia.lock.json"
NVIDIA_OUTPUT_DIRECTORY = "nvidia"
NVIDIA_REPORT_NAME = "results.json"
NVIDIA_LOCK_COPY = "sources/nvidia.lock.json"
NVIDIA_VERIFICATION_NAME = "nvidia-verification.json"
NVIDIA_KMOD_PACKAGE = "kmod-apex-nvidia-open"
KERNEL_CONFIG_NAME = "kernel-config.txt"
VENTOY_LOCK_PATH = "config/ventoy-test.lock.json"
VENTOY_INPUTS_DIRECTORY = "ventoy-inputs"
VENTOY_SUMS_NAME = "ventoy-sha256.txt"
VENTOY_WORK_DIRECTORY = "ventoy"
LIVE_ISO_RELATIVE = "live/Apex-Live.iso"
GPGV_HOME = "gpgv"
GPGV_DEADLINE = timing.Deadline(timing.Elapsed(60))
UBUNTU_SIGNATURE_LOG = "ubuntu-signature.log"
UBUNTU_VERIFICATION_NAME = "ubuntu-verification.json"
LIVE_VERIFICATION_NAME = "live-verification.json"
INPUTS_LOCK_NAME = "inputs.lock.json"
MEDIA_EXECUTION_NAME = "execution.json"
FINGERPRINT_OBSERVATIONS_DIRECTORY = "fingerprint-observations"
TRACE_EVENTS_NAME = "events.jsonl"
TRACE_SUMMARY_NAME = "summary.json"
TRACE_EVENT_LIMIT = 2000
TRACE_ERROR_LIMIT = 20
TRACE_LINE_LIMIT = bounded.Limit(256 * 1024)
TRACE_RAW_LIMIT = bounded.Limit(256 * 1024)
BUS_QUERY_DEADLINE = timing.Deadline(timing.Elapsed(2))
KERNEL_RELEASE = "/proc/sys/kernel/osrelease"
DIALOG_TESTS_DIRECTORY = "fingerprint-dialog-tests"
ELAN_TESTS_DIRECTORY = "elan-diagnostics-tests"
DIALOG_LOCK_PATH = "config/gnome-fingerprint.lock.json"
ELAN_LOCK_PATH = "config/elan-diagnostics.lock.json"
DIALOG_HARNESS_PATH = "tests/fixtures/fingerprint-dialog-harness.c"
ELAN_HARNESS_PATH = "tests/fixtures/elan-diagnostics-harness.c"
PATCH_WORK_DIRECTORY = "work"
COMPILE_DEADLINE = timing.Deadline(timing.Elapsed(300))
HARNESS_CASE_DEADLINE = timing.Deadline(timing.Elapsed(5))
COMPACTIONS_DIRECTORY = "compactions"
COMPRESSED_DISK_NAME = "builder-compressed.qcow2"
CONVERT_LOG_NAME = "convert.log"
FINALISE_PREFIX = "finalize-"
COMPACTION_RESERVE = quantities.Gib(4)
COMPACTION_DEADLINE = timing.Deadline(timing.Elapsed(4 * 3600))
COMPRESSION_TYPE = "zstd"
CONVERT_THREADS = "2"
FINGERPRINT_RPMS_LOCK_PATH = "config/fingerprint-rpms.lock.json"
FINGERPRINT_REQUEST_NAME = "fingerprint-request.json"
FINGERPRINT_INPUTS_DIRECTORY = "inputs"
FINGERPRINT_PACKAGES_DIRECTORY = "packages"
FINGERPRINT_MOCK_DIRECTORY = "mock"
FINGERPRINT_REPODATA_PREFIX = "packages/repodata/"
FINGERPRINT_VENDOR_SUFFIX = "apex1"
FINGERPRINT_VERIFICATION_NAME = "verified.json"
UPDATE_WORK_PREFIX = "/var/tmp/apex-update-"
GRUB_REPAIR_PATH = "guest/fix-grub-fragment.py"
RETRY_PRESET_PATH = "system_files/usr/share/apex/greenboot.conf"
FIXTURE_DISK_NAME = "fixture-disk.json"
FIXTURE_DISK_SCOPE = "Fresh installed recovery fixture; boot is NOT TESTED"
FINGERPRINT_TEST_LOCK = safepaths.RemotePath("/run/apex-fingerprint-test.lock")
SMOKE_SCRIPT_NAME = "test.py"
SMOKE_INPUTS_NAME = "inputs.json"
SMOKE_LOG_NAME = "test.log"
GTK_REQUEST_NAME = "request.json"
GTK_LOG_NAME = "execution.log"
GTK_LOCK_NAME = "test.lock"
GTK_INPUT_FILES = (
    "guest/fingerprint-gtk.py",
    "guest/fingerprint-gtk.c",
    "guest/fingerprint-gtk-service.py",
    "config/fingerprint-rpms.lock.json",
    "rpms/patches/gnome-fingerprint-retain-claim.patch",
)
SMOKE_SCRIPT_PATH = "guest/fingerprint-rpm-smoke.py"

CHECK_DEADLINE = timing.Deadline(timing.Elapsed(1800))
CHECK_OUTPUT_LIMIT = bounded.Limit(16 * 1024 * 1024)
GUEST_READY = timing.WaitPolicy(
    deadline=timing.Deadline(timing.Elapsed(240)),
    backoff=timing.Backoff.exponential(
        first=timing.Elapsed(2), ceiling=timing.Elapsed(2), factor=1
    ),
    description="the guest answers over ssh and systemd reports the system running",
)
SYSTEM_STATES = frozenset({"running", "degraded"})
REBOOT_EXITS = frozenset({0, 255})
UPDATE_OPERATION_DEADLINE = timing.Deadline(timing.Elapsed(900))
UPDATE_UPLOAD_PREFIX = "/var/tmp/apex-update-"
UPDATE_SENTINEL_NAME = "apex-update-sentinel.txt"
UPDATE_REPORT_NAME = "update.json"
RECOVERY_REPORT_NAME = "recovery.json"
INITRAMFS_REPORT_NAME = "initramfs.json"
