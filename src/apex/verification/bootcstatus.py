"""The deployment status as a guest reported it, read on the host and compared, never more."""

from __future__ import annotations

from apex.kernel import encoding, errors, refusals

STATUS = "status"
IMAGE = "image"
IMAGE_DIGEST = "imageDigest"
BOOTED = "booted"
ROLLBACK = "rollback"
STAGED = "staged"


def unexpected(detail: str) -> errors.Refusal:
    return errors.Refusal(refusals.RefusalReason.UPDATE_STATE_UNEXPECTED, subject=detail)


def image(status: encoding.JsonValue, slot: str) -> str | None:
    """The image digest the named deployment slot carries, or nothing when the slot is empty."""
    inner = status.get(STATUS) if isinstance(status, dict) else None
    deployment = inner.get(slot) if isinstance(inner, dict) else None
    held = deployment.get(IMAGE) if isinstance(deployment, dict) else None
    digest = held.get(IMAGE_DIGEST) if isinstance(held, dict) else None
    return digest if isinstance(digest, str) and digest else None


def require_booted(status: encoding.JsonValue, expected: str) -> None:
    if image(status, BOOTED) != expected:
        raise unexpected("the booted deployment is not the selected fixture image")


def parse(observation: encoding.JsonValue) -> encoding.Document:
    """The status document out of a program observation that captured bootc's output."""
    if not isinstance(observation, dict) or observation.get("returncode") != 0:
        raise unexpected("bootc status did not succeed in the guest")
    try:
        return encoding.parse_object(str(observation.get("stdout", "")).encode())
    except ValueError as malformed:
        raise unexpected(f"bootc status is not a document: {malformed}") from malformed
