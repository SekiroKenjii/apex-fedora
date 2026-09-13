"""The initramfs fault operations, and the review an injection is bound to.

An injection takes the result of an inspection the operator reviewed: the same fixture,
the same images, the same machine, and the plan digest the guest computed, which the guest
compares again before it changes anything.
"""

from __future__ import annotations

from apex.kernel import encoding, errors, refusals

NAME = "initramfs"
INSPECT = "inspect"
INJECT = "inject"
RESCUE = "verify-rescue"
ACTIONS = (INSPECT, INJECT, RESCUE)
PASS = "PASS"
BLOCKED = "BLOCKED"


def _mismatch(detail: str) -> errors.Refusal:
    return errors.Refusal(
        refusals.RefusalReason.INSPECTION_MISMATCH,
        subject=detail,
        remedy="inspect this machine with this fixture again and review the result",
    )


def require_inspection(
    inspection: encoding.Document, *, fixture: str, images: encoding.Document, process: int
) -> str:
    """The reviewed plan's digest, from an inspection of this fixture on this machine."""
    if inspection.get("status") != PASS or inspection.get("action") != INSPECT:
        raise _mismatch("the inspection did not pass, or is not an inspection")
    if inspection.get("fixture") != fixture or inspection.get("images") != images:
        raise _mismatch("the inspection is of another fixture")
    if inspection.get("machine_process") != process:
        raise _mismatch("the inspection is of another machine")
    guest = inspection.get("guest")
    digest = guest.get("sha256") if isinstance(guest, dict) else None
    if not isinstance(digest, str) or not digest:
        raise _mismatch("the inspection carries no plan digest")
    return digest
