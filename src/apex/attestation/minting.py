"""Writing one result into the store, with every refusal made before the first byte lands.

The older tool checked a proof's suffix, a hardware check's environment and a passing result's
proofs on the way in, and the readiness fold checks the same things on the way out. Both
boundaries stay. A record that could not have been written is still judged when it is read,
because the store on disk is not trusted to have come from this code.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence

from apex.attestation import catalogue, ledger, proofs
from apex.kernel import claims, errors, identifiers, refusals, verdicts
from apex.registry import descriptors


@dataclasses.dataclass(frozen=True, slots=True)
class Offered:
    """Bytes a stage wants filed as proof, with the kind the older tool judged by suffix."""

    payload: bytes
    kind: str


@dataclasses.dataclass(frozen=True, slots=True)
class Minted:
    sealed: ledger.Sealed
    proofs: tuple[proofs.Proof, ...]

    @property
    def check(self) -> identifiers.CheckId:
        return self.sealed.entry.event.check


def _refuse(reason: refusals.RefusalReason, subject: str, remedy: str) -> errors.Refusal:
    return errors.Refusal(reason, subject=subject, remedy=remedy)


def _specification(check: identifiers.CheckId) -> descriptors.CheckSpec:
    if str(check) not in catalogue.sealed():
        raise _refuse(
            refusals.RefusalReason.UNKNOWN_CHECK,
            str(check),
            "a result is recorded only for a check the catalogue declares",
        )
    return catalogue.specification(check)


def _require_environment(spec: descriptors.CheckSpec, witnessed: claims.EnvironmentKind) -> None:
    physical = claims.EnvironmentKind.PHYSICAL
    if spec.group == descriptors.HARDWARE_GROUP and witnessed is not physical:
        raise _refuse(
            refusals.RefusalReason.HARDWARE_REQUIRES_PHYSICAL,
            f"{spec.id} was witnessed in {witnessed}",
            "hardware evidence comes from the laptop, never from a virtual machine",
        )
    claims.require_attestable(witnessed, expected=spec.environment)


def _intended(spec: descriptors.CheckSpec, offered: Sequence[Offered]) -> tuple[proofs.Proof, ...]:
    """Every citation, judged before any byte is filed; `Proof` refuses an empty one."""
    accepted = set(spec.accepted_proof_kinds)
    for item in offered:
        if item.kind not in accepted:
            raise _refuse(
                refusals.RefusalReason.PROOF_KIND_NOT_ACCEPTED,
                f"{spec.id} does not accept {item.kind}",
                f"offer one of {', '.join(spec.accepted_proof_kinds)}",
            )
    return tuple(
        proofs.Proof(
            digest=proofs.address(item.payload), kind=item.kind, byte_count=len(item.payload)
        )
        for item in offered
    )


def _require_proof_for_pass(
    spec: descriptors.CheckSpec, verdict: verdicts.Verdict, offered: Sequence[Offered]
) -> None:
    if verdict == verdicts.PASSED and not offered:
        raise _refuse(
            refusals.RefusalReason.PASS_REQUIRES_PROOF,
            str(spec.id),
            "a passing result files at least one proof",
        )


def mint(
    *,
    check: identifiers.CheckId,
    verdict: verdicts.Verdict,
    offered: Sequence[Offered],
    candidate: identifiers.Digest,
    witnessed: claims.EnvironmentKind,
    store: proofs.ProofStore,
    chain: ledger.Ledger,
    scope_limits: Sequence[claims.ScopeLimit] = (),
) -> Minted:
    """Refuse, then absorb every proof, then append. Nothing is filed before the last refusal.

    `witnessed` is what the bundle that ran the check reports, never an argument a stage
    chose; the caller passes `ports.environment` and the type makes no other value easier.
    """
    spec = _specification(check)
    _require_environment(spec, witnessed)
    intended = _intended(spec, offered)
    _require_proof_for_pass(spec, verdict, offered)
    filed = tuple(store.absorb(item.payload, kind=item.kind) for item in offered)
    if filed != intended:
        raise errors.InternalDefect(f"{check}: the store filed other proofs than were offered")
    sealed = chain.append(
        ledger.Event(
            kind=ledger.EntryKind.RECORDED,
            check=check,
            verdict=verdict,
            environment=witnessed,
            candidate=candidate,
            proofs=tuple(item.digest for item in filed),
            scope_limits=tuple(scope_limits),
        )
    )
    return Minted(sealed=sealed, proofs=filed)
