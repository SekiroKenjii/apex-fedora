"""An observation the host has judged, held with the proof the verdict cites.

A probe reports and never judges. The judgement is the host's, made from the report and
from what the host captured, and it is filed as proof beside the report so a reader can
re-run it over the same bytes. A fault report is the same shape, judged by the guest's own
status; the minting stage files either kind and folds their verdicts alike.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from apex.attestation import minting
from apex.kernel import encoding, verdicts
from apex.pipeline import facts

REPORT_KIND = ".json"
VERDICT = "verdict"
BLOCKED_BY = "blocked_by"
EARLIER_VERDICT = "earlier_verdict"


class Evidence(Protocol):
    """What the minting stage needs from a report: its verdict, its proof, and any more proof."""

    @property
    def verdict(self) -> verdicts.Verdict: ...

    @property
    def proof(self) -> minting.Offered: ...

    @property
    def extras(self) -> tuple[minting.Offered, ...]: ...


@dataclasses.dataclass(frozen=True, slots=True)
class Judged:
    observations: encoding.Document
    verdict: verdicts.Verdict
    proof: minting.Offered
    extras: tuple[minting.Offered, ...] = ()


def judge(
    observations: encoding.Document,
    verdict: verdicts.Verdict,
    *,
    extras: Sequence[minting.Offered] = (),
) -> Judged:
    """The observations with the verdict written into them, canonically encoded as proof."""
    document: encoding.Document = {**observations, VERDICT: verdict.stored_name}
    return Judged(
        observations=document,
        verdict=verdict,
        proof=minting.Offered(payload=encoding.canonical(document), kind=REPORT_KIND),
        extras=tuple(extras),
    )


def capture(payload: bytes, *, name: str) -> minting.Offered:
    """A captured file offered as proof under the kind its name carries."""
    return minting.Offered(payload=payload, kind=Path(name).suffix)


def blocked_by(
    held: facts.FactMap, gates: Sequence[facts.FactKey[Judged]]
) -> Judged | None:
    """A BLOCKED judgement naming the first earlier one that did not pass, or nothing.

    A stage that needs the guest in the state an earlier stage proved does not ask the
    guest for what it cannot do; it blocks itself on that stage's name, so the record
    carries the first failure and nothing after it is mistaken for a second one.
    """
    for gate in gates:
        earlier = held[gate]
        if earlier.verdict is not verdicts.PASSED:
            return judge(
                {BLOCKED_BY: str(gate), EARLIER_VERDICT: earlier.verdict.stored_name},
                verdicts.BLOCKED,
            )
    return None
