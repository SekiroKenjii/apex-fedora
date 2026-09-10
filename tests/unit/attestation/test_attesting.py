"""What an imported record is, and what importing permanently costs it.

Two limits are properties of the v1 format rather than of any one record. Its environment came
from an argument instead of from the port that ran the check, and its binding to a candidate
was never read back off the artifact. Re-hashing the proofs retires neither, so a value that
lacks them cannot be constructed at all.
"""

from __future__ import annotations

import pytest

from apex.attestation import attesting, ledger, readiness
from apex.kernel import claims, errors, identifiers, verdicts

CANDIDATE = identifiers.Digest("c" * 64)


def resolved(*, imported: bool) -> readiness.ResolvedRecord:
    return readiness.ResolvedRecord(
        check=identifiers.CheckId("build.one"),
        verdict=verdicts.PASSED,
        environment=claims.EnvironmentKind.BUILD,
        candidate=CANDIDATE,
        proofs_intact=True,
        proof_count=1,
        imported=imported,
    )


def test_an_imported_attestation_carries_both_permanent_limits() -> None:
    entry = attesting.Attestation(
        kind=ledger.EntryKind.IMPORTED,
        resolved=resolved(imported=True),
        limits=attesting.LEGACY_LIMITS,
        origin="audio.json",
    )

    assert claims.ScopeLimit.LEGACY_NO_PORT_PROOF in entry.limits
    assert claims.ScopeLimit.LEGACY_NO_CANDIDATE_READBACK in entry.limits
    assert entry.check == "build.one"


@pytest.mark.parametrize(
    "dropped",
    [
        claims.ScopeLimit.LEGACY_NO_PORT_PROOF,
        claims.ScopeLimit.LEGACY_NO_CANDIDATE_READBACK,
    ],
)
def test_an_imported_attestation_missing_either_permanent_limit_is_a_defect(
    dropped: claims.ScopeLimit,
) -> None:
    with pytest.raises(errors.InternalDefect):
        attesting.Attestation(
            kind=ledger.EntryKind.IMPORTED,
            resolved=resolved(imported=True),
            limits=attesting.LEGACY_LIMITS - {dropped},
            origin="audio.json",
        )


def test_an_attestation_whose_kind_and_record_disagree_is_a_defect() -> None:
    """The lock that stops a reader declaring imported while emitting unmarked records."""
    with pytest.raises(errors.InternalDefect):
        attesting.Attestation(
            kind=ledger.EntryKind.IMPORTED,
            resolved=resolved(imported=False),
            limits=attesting.LEGACY_LIMITS,
            origin="audio.json",
        )


def test_a_recorded_attestation_may_not_carry_a_legacy_limit() -> None:
    with pytest.raises(errors.InternalDefect):
        attesting.Attestation(
            kind=ledger.EntryKind.RECORDED,
            resolved=resolved(imported=False),
            limits=frozenset({claims.ScopeLimit.LEGACY_NO_PORT_PROOF}),
            origin="audio.json",
        )


def test_a_recorded_attestation_over_an_unmarked_record_is_accepted() -> None:
    entry = attesting.Attestation(
        kind=ledger.EntryKind.RECORDED,
        resolved=resolved(imported=False),
        limits=frozenset(),
        origin="build.one",
    )

    assert entry.limits == frozenset()
