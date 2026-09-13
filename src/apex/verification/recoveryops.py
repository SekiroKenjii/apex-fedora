"""The recovery operations the older tool performed on an installed disposable guest.

Each action is one inspection or one change against a completed update fixture: the boot
state read, the installed configuration verified, a diagnostic change made in a private
mount namespace, a reboot requested, or the evidence collected after it. None of them is a
release migration, and the scope text says so in every report.
"""

from __future__ import annotations

import hashlib

from apex.kernel import encoding, errors, identifiers, refusals
from apex.verification import bootcstatus

NAME = "recovery"
INSPECT = "inspect"
VERIFY_INSTALLED = "verify-installed"
NATIVE_MIGRATION = "native-migration"
REPAIR_GRUB = "repair-grub"
ARM_GDM = "arm-gdm"
RETRY_CONFIG = "retry-config"
REBOOT = "reboot"
COLLECT = "collect"
ACTIONS = (
    INSPECT, VERIFY_INSTALLED, NATIVE_MIGRATION, REPAIR_GRUB, ARM_GDM, RETRY_CONFIG, REBOOT,
    COLLECT,
)
MUTATIONS = frozenset({REPAIR_GRUB, ARM_GDM, RETRY_CONFIG})
CANDIDATE_BOUND = MUTATIONS | {NATIVE_MIGRATION, REBOOT}
SCOPE = "Recovery fixture only, not frozen candidate acceptance"
REBOOT_SCOPE = "One guest reboot requested; recovery is NOT TESTED until collection"
MIGRATION_BLOCKED = "BLOCKED: this command does not refresh an existing static configuration"


def preimage(inspection: encoding.Document) -> str:
    """The digest of the installed GRUB configuration as the inspection read it."""
    observed = inspection.get("grub_config")
    text = str(observed.get("stdout", "")) if isinstance(observed, dict) else ""
    return hashlib.sha256(text.encode()).hexdigest()


def require_staged(status: encoding.JsonValue, expected: str) -> None:
    if bootcstatus.image(status, bootcstatus.STAGED) != expected:
        raise bootcstatus.unexpected("stage the signed B fixture before the initial fault reboot")


def require_preset(preset: identifiers.Digest | None) -> str:
    if preset is None:
        raise errors.Refusal(
            refusals.RefusalReason.FIXTURE_REPORT_MALFORMED,
            subject="use a fixture built with a recorded recovery preset",
        )
    return preset.hex
