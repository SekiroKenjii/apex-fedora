"""The strict readiness view, reached from the pre-restructure command surface.

This is a bridge and it is deleted at cutover. It exists so the operator can see which results
the project is standing on before the new command surface arrives.

Every refusal from the new tree is translated here. `errors.Refusal` is not in the exception
tuple the old entry point catches, so a corrupt or forward-versioned mark would otherwise reach
the operator as a stack trace on the strict command while the permissive one kept working.
"""

from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

from apexlib.common import Blocked

REPOSITORY = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPOSITORY / "src")]

from apex.attestation import columns, readiness, reading, resolving, retracting  # noqa: E402
from apex.cli import rendering  # noqa: E402
from apex.kernel import errors  # noqa: E402


@dataclasses.dataclass(frozen=True)
class View:
    text: str
    refusal: str | None


def _refusal(table: columns.Table) -> str | None:
    if table.ready:
        return None
    return (
        f"Installation is blocked: {table.imported} of {len(table.rows)} results were "
        "imported from the store the earlier tools wrote. No port witnessed them and no "
        "candidate was read back, so they cannot carry an installation."
    )


def _build(state: Path, *, strict: bool) -> View:
    found = reading.read_store(state)
    outcome = readiness.evaluate(
        required=resolving.required_environments(),
        records=found.records,
        candidate=found.candidate,
    )
    withheld: tuple[retracting.Withheld, ...] = ()
    if strict:
        outcome, withheld = retracting.retract(outcome, attestations=found.attestations)
    table = columns.tabulate(
        reading=found, outcome=outcome, withheld=withheld, strict=strict
    )
    return View(text=rendering.render(table), refusal=_refusal(table))


def strict_view(state: Path) -> View:
    try:
        return _build(state, strict=True)
    except errors.ApexError as failure:
        raise Blocked(str(failure)) from failure


def readiness_refusal(state: Path) -> str | None:
    try:
        return _build(state, strict=False).refusal
    except errors.ApexError as failure:
        raise Blocked(str(failure)) from failure
