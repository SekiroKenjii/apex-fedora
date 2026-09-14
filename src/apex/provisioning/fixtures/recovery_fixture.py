"""Diagnostic changes to an installed disposable guest, never a release migration.

Three derivations are pure and live here: the exact newline repair of the installed GRUB
configuration, the observer program armed on the next boot of B, and the one-retry variant of
the greenboot configuration. Each refuses a preimage it does not recognise.
"""

from __future__ import annotations

from collections.abc import Mapping

from apex.kernel import errors, identifiers, refusals, safepaths

BROKEN = b"save_env boot_success### END 08_greenboot.cfg ###"
FIXED = b"save_env boot_success\n### END 08_greenboot.cfg ###"
FRAGMENT_TAIL = b"save_env boot_success\n"
RETRIES_BEFORE = b"GREENBOOT_MAX_BOOT_ATTEMPTS=2\n"
RETRIES_AFTER = b"GREENBOOT_MAX_BOOT_ATTEMPTS=1\n"
EXPECTED_COMPONENTS: Mapping[str, str] = {"bootupd": "0.2.35", "greenboot": "0.16.4"}
OBSERVED_EXIT = 42
DROP_IN = "90-apex-recovery-test.conf"
INTERPRETER = "/usr/bin/python3"
GREENBOOT_CONFIG = "/etc/greenboot/greenboot.conf"
SYSTEMD_UNITS = "/etc/systemd/system"
TEST_DIRECTORY = "/var/lib/apex-recovery-test"


def repaired_config(current: bytes, fragment: bytes) -> bytes:
    if not fragment.endswith(FRAGMENT_TAIL):
        raise _unexpected("the image fragment must already contain the reviewed newline repair")
    if current.count(BROKEN) != 1 or FIXED in current:
        raise _unexpected("an unknown or already repaired installed configuration")
    return current.replace(BROKEN, FIXED)


def retry_config(before: bytes) -> bytes:
    if before.count(RETRIES_BEFORE) != 1:
        raise _unexpected("expected the original two-retry fixture configuration")
    return before.replace(RETRIES_BEFORE, RETRIES_AFTER)


def observer_program(bad: identifiers.ImageId, destination: safepaths.RemotePath) -> str:
    """The program that records each boot phase and fails gdm once on the faulted B."""
    return f"""#!/usr/bin/python3
import json
import os
from pathlib import Path
import subprocess
import sys

root = Path({str(destination)!r})
boot_id = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
def capture(args):
    p = subprocess.run(args, text=True, capture_output=True)
    return {{'returncode': p.returncode, 'stdout': p.stdout, 'stderr': p.stderr}}
status = capture(['bootc', 'status', '--json'])
current = json.loads(status['stdout'])['status']['booted']['image']['imageDigest']
phase = sys.argv[1]
record = {{'boot_id': boot_id, 'phase': phase, 'digest': current, 'bootc': status,
          'grubenv': capture(['grub2-editenv', '-', 'list']),
          'gdm': capture(['systemctl', 'show', 'gdm.service', '-p', 'ActiveState', '-p', 'Result']),
          'injected': phase == 'gdm-start' and current == {str(bad)!r}}}
path = root / (boot_id + '-' + phase + '.json')
with path.open('w') as stream:
    json.dump(record, stream)
    stream.flush()
    os.fsync(stream.fileno())
print('APEX_RECOVERY_OBSERVATION ' + json.dumps(record), flush=True)
if record['injected']:
    sys.exit({OBSERVED_EXIT})
"""


def unit_overrides(program: safepaths.RemotePath) -> Mapping[str, str]:
    """The systemd drop-ins that run the observer around gdm and the health check."""
    return {
        "gdm.service": (f"[Service]\nRestart=no\nExecStartPre={INTERPRETER} {program} gdm-start\n"),
        "greenboot-healthcheck.service": (
            f"[Service]\nExecStartPre={INTERPRETER} {program} health-before\n"
            f"ExecStopPost={INTERPRETER} {program} health-after\n"
        ),
    }


def _unexpected(detail: str) -> errors.Refusal:
    return errors.Refusal(refusals.RefusalReason.FIXTURE_STATE_UNEXPECTED, subject=detail)
