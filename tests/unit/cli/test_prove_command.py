"""A check proven on the host is recorded through the real ports, and the record it makes
supersedes the one imported from the older tree for the same check."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pretendingreal import pretending_real
from signedbundle import BUILD, SIGNED_DIGEST, keys, signed_output

from apex.adapters.fakes import fake_signing
from apex.adapters.real import real_clock, real_digesting, real_files, real_ids, real_process
from apex.attestation import ledger, reading
from apex.cli import commandspecs
from apex.cli.commands import prove_command
from apex.config import defaults, loader
from apex.kernel import claims, errors, refusals, safepaths
from apex.ports import portset
from apex.wiring import contexts

REPOSITORY = Path(__file__).resolve().parents[3]
CANDIDATE = "sha256:" + "c" * 64
LEGACY = {
    "check": "git.commit-policy",
    "digest": CANDIDATE,
    "status": "PASS",
    "environment": {"kind": "build", "description": "Local Git fixtures"},
    "recorded_at": "2026-01-01T00:00:00+00:00",
    "reason": "",
    "proof": [],
}


def real_host() -> portset.HostPorts:
    """The ports a host proof reaches: real processes, files, digests, identities and clock."""
    return pretending_real(
        processes=real_process.SubprocessRunner(),
        files=real_files.LocalFiles(),
        digests=real_digesting.CachedDigests(),
        identities=real_ids.RandomIdentities(),
        clock=real_clock.SystemClock(),
    )


def runtime(tmp_path: Path, digest: str) -> safepaths.RuntimeRoot:
    base = tmp_path / "runtime"
    base.mkdir(mode=0o700)
    (base / "candidate.json").write_text(json.dumps({"digest": digest, "build_id": "b" * 32}))
    return safepaths.RuntimeRoot.adopt(base)


@pytest.fixture
def root(tmp_path: Path) -> safepaths.RuntimeRoot:
    return runtime(tmp_path, CANDIDATE)


def request(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot | None, *arguments: str
) -> commandspecs.Request:
    return commandspecs.Request(
        arguments=arguments,
        context=contexts.Context(
            settings=loader.load(host_file=None, environment={}),
            repository=safepaths.SourceRoot.adopt(REPOSITORY),
            root=root,
            environment={},
            bundle=lambda _root: ports,
        ),
    )


def recorded(reply: commandspecs.Reply) -> list[dict[str, Any]]:
    assert isinstance(reply.document, dict)
    listed = reply.document["recorded"]
    assert isinstance(listed, list)
    return [dict(item) for item in listed]  # type: ignore[call-overload]


def test_the_three_git_checks_are_proven_over_disposable_repositories_and_recorded(
    root: safepaths.RuntimeRoot,
) -> None:
    ports = real_host()

    reply = prove_command.run(request(ports, root, "git"))

    assert reply.exit_code == 0
    assert [(item["check"], item["verdict"], item["sequence"]) for item in recorded(reply)] == [
        ("git.commit-policy", "PASS", 0),
        ("git.private-stage", "PASS", 1),
        ("git.outgoing-history", "PASS", 2),
    ]
    assert all(len(item["proofs"]) == 1 for item in recorded(reply))
    found = reading.read_store(root.path, files=ports.files)
    assert found.version == 2
    assert [item.check for item in found.attestations] == [
        "git.commit-policy",
        "git.outgoing-history",
        "git.private-stage",
    ]
    for item in found.attestations:
        assert item.kind is ledger.EntryKind.RECORDED and item.limits == frozenset()
        assert item.resolved.environment is claims.EnvironmentKind.BUILD
        assert item.resolved.proofs_intact and item.resolved.proof_count == 1
    (scratch,) = (root.path / defaults.GIT_PROOFS_DIRECTORY).iterdir()
    assert sorted(path.name for path in scratch.iterdir()) == [
        "commit-policy",
        "outgoing-history",
        "private-stage",
    ]


def test_a_recorded_proof_supersedes_the_record_imported_for_the_same_check(tmp_path: Path) -> None:
    root = runtime(tmp_path, CANDIDATE)
    (root.path / "evidence").mkdir()
    (root.path / "evidence" / "git.commit-policy.json").write_text(json.dumps(LEGACY))
    ports = real_host()
    before = reading.read_store(root.path, files=ports.files)

    prove_command.run(request(ports, root, "git"))

    after = reading.read_store(root.path, files=ports.files)
    (imported,) = before.attestations
    (kept,) = [item for item in after.attestations if item.check == "git.commit-policy"]
    assert imported.kind is ledger.EntryKind.IMPORTED and imported.limits
    assert kept.kind is ledger.EntryKind.RECORDED and kept.limits == frozenset()
    assert kept.origin == "chain#0"


def test_a_hook_that_permits_everything_is_recorded_as_a_failure_and_fails_the_command(
    root: safepaths.RuntimeRoot, monkeypatch: pytest.MonkeyPatch
) -> None:
    ports = real_host()
    monkeypatch.setattr(prove_command, "_inspect", lambda _ports: lambda *_: ())

    reply = prove_command.run(request(ports, root, "git"))

    assert reply.exit_code == prove_command.FAILED_EXIT
    assert [(item["check"], item["verdict"]) for item in recorded(reply)] == [
        ("git.commit-policy", "FAIL"),
        ("git.private-stage", "FAIL"),
        ("git.outgoing-history", "FAIL"),
    ]


def test_a_simulated_bundle_cannot_record_a_proof(root: safepaths.RuntimeRoot) -> None:
    simulated = pretending_real(
        processes=real_process.SubprocessRunner(),
        files=real_files.LocalFiles(),
        signing=fake_signing.FakeSigner(),
    )

    with pytest.raises(errors.Refusal) as refused:
        prove_command.run(request(simulated, root, "git"))

    assert refused.value.reason is refusals.RefusalReason.SIMULATED_ENVIRONMENT
    assert not (root.path / "attestation" / "ledger" / "chain.jsonl").exists()


def test_the_signature_checks_are_recorded_for_the_candidates_build(tmp_path: Path) -> None:
    root = runtime(tmp_path, SIGNED_DIGEST)
    ports = pretending_real(files=real_files.LocalFiles(), digests=real_digesting.CachedDigests())
    private, public = keys(ports, root)
    signed_output(ports, root, private)

    reply = prove_command.run(
        request(ports, root, "signature", "--build", str(BUILD), "--key", str(public))
    )

    assert reply.exit_code == 0
    assert [(item["check"], item["verdict"], item["sequence"]) for item in recorded(reply)] == [
        ("signature.accept", "PASS", 0),
        ("signature.reject", "PASS", 1),
    ]
    found = reading.read_store(root.path, files=ports.files)
    assert [item.check for item in found.attestations] == ["signature.accept", "signature.reject"]
    assert all(item.kind is ledger.EntryKind.RECORDED for item in found.attestations)
    (exercised,) = (root.path / defaults.SIGNATURE_TESTS_DIRECTORY).iterdir()
    assert (exercised / defaults.RESULTS_NAME).is_file()


def test_a_build_that_is_not_the_candidate_is_refused_before_anything_is_recorded(
    root: safepaths.RuntimeRoot,
) -> None:
    ports = pretending_real(files=real_files.LocalFiles(), digests=real_digesting.CachedDigests())
    private, public = keys(ports, root)
    signed_output(ports, root, private)

    with pytest.raises(errors.Refusal) as refused:
        prove_command.run(
            request(ports, root, "signature", "--build", str(BUILD), "--key", str(public))
        )

    assert refused.value.reason is refusals.RefusalReason.RECORD_NOT_BOUND_TO_CANDIDATE
    assert not (root.path / "attestation" / "ledger" / "chain.jsonl").exists()


def test_proving_needs_a_runtime_root_and_a_selected_candidate(tmp_path: Path) -> None:
    ports = real_host()
    empty = tmp_path / "empty"
    empty.mkdir(mode=0o700)

    with pytest.raises(errors.PreconditionUnmet):
        prove_command.run(request(ports, None, "git"))
    with pytest.raises(errors.PreconditionUnmet) as unmet:
        prove_command.run(request(ports, safepaths.RuntimeRoot.adopt(empty), "git"))

    assert unmet.value.reason is refusals.RefusalReason.PATH_NOT_A_REGULAR_FILE
