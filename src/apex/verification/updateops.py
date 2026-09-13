"""The A/B update operations the older tool performed, and how each outcome is judged.

Each action names one thing done to the disposable guest against a completed update
fixture: the fixture provisioned, the guest switched to A or forward to B, rolled back, asked
to accept a copy that must be rejected, or checked as booted into one version. The judgements
are the older tool's, over what the units observed.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from apex.kernel import encoding, errors, hashing, refusals
from apex.provisioning.fixtures import update_fixture
from apex.verification import bootcstatus

NAME = "update"
PROVISION = "provision"
PROVISION_A = "provision-a"
SWITCH_A = "switch-a"
FORWARD = "forward"
ROLLBACK = "rollback"
WRONG_KEY = "wrong-key"
UNSIGNED = "unsigned"
UNTRUSTED = "untrusted"
CHECK_A = "check-a"
CHECK_B = "check-b"
ACTIONS = (
    PROVISION, PROVISION_A, SWITCH_A, FORWARD, ROLLBACK, WRONG_KEY, UNSIGNED, UNTRUSTED,
    CHECK_A, CHECK_B,
)
PROVISIONS = frozenset({PROVISION, PROVISION_A})
REJECTIONS = frozenset({WRONG_KEY, UNSIGNED, UNTRUSTED})
CHECKS = frozenset({CHECK_A, CHECK_B})
SOURCES: Mapping[str, str] = {
    SWITCH_A: "a", FORWARD: "b", WRONG_KEY: WRONG_KEY, UNSIGNED: UNSIGNED, UNTRUSTED: UNTRUSTED,
}
POLICY_FILE = "policy.json"
SENTINEL_DIGEST = hashing.digest_bytes(update_fixture.SENTINEL_TEXT).hex
REJECTED_BY_POLICY = re.compile("rejected by policy", re.IGNORECASE)
SIGNATURE = re.compile("signature", re.IGNORECASE)
HEALTH_CHECKS = ("gdm", "bootc", "dbus", "root_mount", "failed_units", "selinux", "kernel")
ACTIVE = "active"
ENFORCING = "Enforcing"


def source_directory(fixture: str, action: str) -> str:
    return f"{update_fixture.FIXTURE_ROOT}/{fixture}/{SOURCES[action]}"


def require_rejection(
    case: str, operation: encoding.Document, before: encoding.JsonValue, after: encoding.JsonValue
) -> None:
    """A rejected switch: bootc failed for the policy's reason and nothing was deployed."""
    pattern = REJECTED_BY_POLICY if case == UNTRUSTED else SIGNATURE
    stderr = str(operation.get("stderr", ""))
    if operation.get("returncode") == 0 or not pattern.search(stderr) or before != after:
        raise errors.Refusal(
            refusals.RefusalReason.UPDATE_REJECTION_NOT_OBSERVED,
            subject="expected policy rejection with unchanged deployments was not observed",
        )


def require_switched(
    operation: encoding.Document, after: encoding.JsonValue, expected: str
) -> None:
    if operation.get("returncode") != 0:
        raise bootcstatus.unexpected("bootc switch did not succeed")
    if bootcstatus.image(after, bootcstatus.STAGED) != expected:
        raise bootcstatus.unexpected("staged digest differs from the signed fixture")


def require_rollback_target(before: encoding.JsonValue, expected: str) -> None:
    if bootcstatus.image(before, bootcstatus.ROLLBACK) != expected:
        raise bootcstatus.unexpected("rollback does not point to A")


def require_marker(marker: encoding.JsonValue, fixture: str, version: str) -> None:
    held = marker if isinstance(marker, dict) else {}
    if held.get("fixture") != fixture or held.get("version") != version:
        raise bootcstatus.unexpected("booted immutable marker mismatch")


def require_sentinel(observed: encoding.Document) -> None:
    if observed.get("sha256") != SENTINEL_DIGEST:
        raise bootcstatus.unexpected("user data changed")


def _returncode(observations: encoding.JsonValue, check: str) -> encoding.JsonValue:
    held = observations.get(check) if isinstance(observations, dict) else None
    return held.get("returncode") if isinstance(held, dict) else None


def _stdout(observations: encoding.JsonValue, check: str) -> str:
    held = observations.get(check) if isinstance(observations, dict) else None
    return str(held.get("stdout", "")) if isinstance(held, dict) else ""


def health_problem(observations: encoding.JsonValue, expected: str) -> str | None:
    """The first of the older critical checks that does not hold, or nothing."""
    for check in HEALTH_CHECKS:
        if _returncode(observations, check) != 0:
            return f"guest {check} failed"
    if _stdout(observations, "gdm").strip() != ACTIVE:
        return "gdm is not active"
    if _stdout(observations, "selinux").strip() != ENFORCING:
        return "SELinux is not enforcing"
    if _stdout(observations, "failed_units").strip():
        return "units have failed"
    try:
        status = encoding.parse_object(_stdout(observations, "bootc").encode())
    except ValueError:
        return "bootc status is not a document"
    if bootcstatus.image(status, bootcstatus.BOOTED) != expected:
        return "the booted deployment is not the selected fixture image"
    return None
