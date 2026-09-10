"""A three-point lattice over check outcomes.

Monotonicity is the property the product needs, so it is expressed as a lattice rather
than as a convention someone has to remember. No combination raises a set containing no
pass to a pass.
"""

from __future__ import annotations

import dataclasses
import functools
from collections.abc import Iterable

from apex.kernel import errors, refusals


@dataclasses.dataclass(frozen=True, slots=True)
class Passed:
    stored_name = "PASS"
    permits_installation = True


@dataclasses.dataclass(frozen=True, slots=True)
class Failed:
    stored_name = "FAIL"
    permits_installation = False


@dataclasses.dataclass(frozen=True, slots=True)
class Blocked:
    stored_name = "BLOCKED"
    permits_installation = False


@dataclasses.dataclass(frozen=True, slots=True)
class NotTested:
    reason: refusals.RefusalReason
    stored_name = "NOT TESTED"
    permits_installation = False


type Verdict = Passed | Failed | Blocked | NotTested

PASSED = Passed()
FAILED = Failed()
BLOCKED = Blocked()

_SEVERITY = {"NOT TESTED": 0, "PASS": 1, "BLOCKED": 2, "FAIL": 3}


def parse(stored_name: str, *, reason: refusals.RefusalReason) -> Verdict:
    if stored_name == Passed.stored_name:
        return PASSED
    if stored_name == Failed.stored_name:
        return FAILED
    if stored_name == Blocked.stored_name:
        return BLOCKED
    if stored_name == NotTested.stored_name:
        return NotTested(reason)
    raise errors.Refusal(refusals.RefusalReason.MALFORMED_VERDICT, subject=stored_name)


def meet(left: Verdict, right: Verdict) -> Verdict:
    """Combine two verdicts, keeping the one that claims least."""
    if isinstance(left, NotTested):
        return right
    if isinstance(right, NotTested):
        return left
    return left if _SEVERITY[left.stored_name] >= _SEVERITY[right.stored_name] else right


def fold(verdicts: Iterable[Verdict], *, reason: refusals.RefusalReason) -> Verdict:
    seed: Verdict = NotTested(reason)
    return functools.reduce(meet, verdicts, seed)
