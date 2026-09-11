"""Environment variables this program accepts, declared one by one.

A variable in the namespace that is not declared is a hard error, so a misspelt override is
refused by name instead of changing nothing in silence.
"""

from __future__ import annotations

import dataclasses

NAMESPACE = "APEX_"


@dataclasses.dataclass(frozen=True, slots=True)
class EnvironmentOverride:
    variable: str
    field: str
    summary: str


DECLARED: tuple[EnvironmentOverride, ...] = (
    EnvironmentOverride(
        variable="APEX_STATE_DIR",
        field="runtime_root",
        summary="where the runtime state, exports and evidence live",
    ),
)

# Variables the guest side reads through its own request document rather than through
# settings. They are listed so the loader can tell a typo from a guest concern.
GUEST_VARIABLES = frozenset({
    "APEX_BAD_INITRD", "APEX_DIAGNOSTIC_HELPERS", "APEX_DIALOG_STATE", "APEX_EFFECT_TRACE",
    "APEX_EFI", "APEX_ELAN_STATUS_DIAGNOSTICS", "APEX_EXTRACTED_HANDLERS", "APEX_FAULT",
    "APEX_FINGERPRINT_IMAGE_TEST", "APEX_LINUX", "APEX_RECOVERY_FIXTURE",
    "APEX_RECOVERY_OBSERVATION", "APEX_RECOVERY_REPORT", "APEX_TEST_DIGEST",
    "APEX_TEST_DISK", "APEX_TEST_PASSWORD_FILE", "APEX_TEST_SSH_KEY", "APEX_TEST_USER",
    "APEX_UPDATE_ACCESS", "APEX_UPDATE_ACTION", "APEX_UPDATE_FIXTURE", "APEX_WINDOWS",
    "APEX_WRONG_PUBLIC_KEY",
})
