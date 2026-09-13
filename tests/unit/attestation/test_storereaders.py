"""The store version elects a reader by being a registry key, never by being a branch.

Adding support for a later store is adding a file to `storereaders/`. Two units claiming the
same mark fail the seal and name both, and a mark nobody claims is a fact about this build
rather than a defect in a declaration.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from apex.attestation import electing, markclaims, readerspecs, storereaders
from apex.kernel import errors, refusals
from apex.model import storemark
from apex.ports import files as files_port
from apex.registry import provenance, registry


def reading(
    runtime_root: Path,  # noqa: ARG001
    *,
    spec: readerspecs.StoreReaderSpec,
    files: files_port.FileSystemPort,  # noqa: ARG001
) -> readerspecs.StoreReading:
    return readerspecs.StoreReading(
        version=spec.version, attestations=(), candidate=None, faults=()
    )


def specification(
    *, version: int = 1, marks: tuple[markclaims.MarkClaim, ...] = (markclaims.MarkAbsent(),)
) -> readerspecs.StoreReaderSpec:
    return readerspecs.StoreReaderSpec(
        version=version,
        marks=marks,
        read=reading,
        limits=frozenset(),
        reads_history=False,
        reads_archives=False,
    )


def test_the_absent_mark_and_an_explicit_version_one_elect_the_same_reader() -> None:
    absent = electing.elect(storemark.Unmarked())
    explicit = electing.elect(storemark.Marked(storemark.FIRST_VERSION))

    assert absent is explicit
    assert absent.version == storemark.FIRST_VERSION


def test_an_unreadable_mark_is_refused_and_is_never_read_as_version_one() -> None:
    with pytest.raises(errors.Refusal) as raised:
        electing.elect(storemark.Unreadable("truncated"))

    assert raised.value.reason is refusals.RefusalReason.MALFORMED_STORE_MARK


def test_a_mark_no_reader_claims_reports_an_unsupported_store_version() -> None:
    with pytest.raises(errors.PreconditionUnmet) as raised:
        electing.elect(storemark.Marked(99))

    assert raised.value.reason is refusals.RefusalReason.STORE_VERSION_NOT_SUPPORTED
    assert markclaims.MarkAbsent().key() in str(raised.value)


def test_two_readers_claiming_one_mark_fail_the_seal_naming_both_modules() -> None:
    """A duplicate claim must never surface as 'no reader claims this mark'.

    `SealedRegistry.lookup`, `Registry.add` and `Registry.seal` all raise the same type, so a
    handler around the lookup would swallow the message that names both declaring modules and
    advise adding a third claimant.
    """
    collector: registry.Registry[str, readerspecs.StoreReaderSpec] = registry.Registry(
        "store reader"
    )
    key = markclaims.MarkAbsent().key()
    collector.add(key, specification(), at=provenance.Provenance("first_reader", "read", 1))

    with pytest.raises(errors.RegistrationError) as raised:
        collector.add(key, specification(), at=provenance.Provenance("second_reader", "read", 1))

    assert "first_reader" in str(raised.value)
    assert "second_reader" in str(raised.value)


def test_a_reader_that_claims_no_mark_is_refused_at_declaration() -> None:
    with pytest.raises(errors.RegistrationError):
        specification(marks=())


@pytest.mark.parametrize("field", ["reads_history", "reads_archives"])
def test_a_reader_may_not_declare_that_it_reads_history_or_archives(field: str) -> None:
    """The scope boundary is a refused declaration, not an absence in a function body."""
    with pytest.raises(errors.RegistrationError):
        readerspecs.StoreReaderSpec(
            version=1,
            marks=(markclaims.MarkAbsent(),),
            read=reading,
            limits=frozenset(),
            reads_history=field == "reads_history",
            reads_archives=field == "reads_archives",
        )


def test_a_reader_below_the_first_version_is_refused() -> None:
    with pytest.raises(errors.RegistrationError):
        specification(version=0)


def test_a_reader_declaring_a_limit_reads_as_imported() -> None:
    from apex.attestation import attesting, ledger

    plain = specification()
    legacy = readerspecs.StoreReaderSpec(
        version=1,
        marks=(markclaims.MarkAbsent(),),
        read=reading,
        limits=attesting.LEGACY_LIMITS,
        reads_history=False,
        reads_archives=False,
    )

    assert plain.kind is ledger.EntryKind.RECORDED
    assert legacy.kind is ledger.EntryKind.IMPORTED


def test_every_registered_mark_resolves_to_a_reader_that_claims_it() -> None:
    sealed = storereaders.sealed()

    for key in sealed:
        assert key in {claim.key() for claim in sealed.lookup(key).marks}


def test_the_registered_reader_set_is_not_empty() -> None:
    assert len(storereaders.sealed()) >= 2
