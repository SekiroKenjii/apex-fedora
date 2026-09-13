"""Where a unit works: a directory under the scratch prefix, named for the host's run.

The host names the directory it laid out; a unit accepts it only under the prefix its kind
uses and only when the name is a run identifier, so a request can never point a unit at a
directory the host did not make for this run.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from apex.kernel import encoding, errors, identifiers, refusals, safepaths


def site_of(
    arguments: Mapping[str, encoding.JsonValue], *, prefix: str
) -> tuple[safepaths.SafePath, identifiers.RunId]:
    value = arguments.get("work")
    if not isinstance(value, str) or not value.startswith(prefix):
        raise errors.Refusal(
            refusals.RefusalReason.REQUEST_MALFORMED,
            subject=f"work must be a directory under {prefix}",
        )
    try:
        run_id = identifiers.RunId.parse(value.removeprefix(prefix))
    except errors.Refusal as fault:
        raise errors.Refusal(
            refusals.RefusalReason.REQUEST_MALFORMED, subject="work must be named for its run"
        ) from fault
    return safepaths.SafePath(Path(value)), run_id
