"""The readiness and evidence commands read a store and never write one."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from apex.adapters.fakes import fake_clock, fake_files, fake_ids
from apex.attestation import catalogue, minting
from apex.cli import commandspecs
from apex.cli.commands import evidence_command, readiness_command
from apex.config import loader
from apex.kernel import identifiers, quantities, safepaths, verdicts
from apex.model import storemark
from apex.ports import portset
from apex.verification import recording
from apex.wiring import contexts

REPOSITORY = Path(__file__).resolve().parents[3]
CANDIDATE = identifiers.Digest("d" * 64)
RECORD = quantities.FileMode(0o600)


@pytest.fixture
def root(tmp_path: Path) -> safepaths.RuntimeRoot:
    base = tmp_path / "runtime"
    base.mkdir(mode=0o700)
    return safepaths.RuntimeRoot.adopt(base)


def recorded_store(root: safepaths.RuntimeRoot, checks: int) -> fake_files.MemoryFiles:
    files = fake_files.MemoryFiles()
    recorder = recording.Recorder.open(
        root, filesystem=files, identities=fake_ids.SequenceIdentities(),
        clock=fake_clock.ManualClock(),
    )
    for spec in list(catalogue.sealed().values())[:checks]:
        recorder.record(
            check=spec.id, verdict=verdicts.PASSED,
            offered=[minting.Offered(payload=b"proof", kind=spec.accepted_proof_kinds[0])],
            candidate=CANDIDATE, witnessed=spec.environment,
        )
    (root.path / storemark.MARK_NAME).write_bytes(storemark.document(storemark.SECOND_VERSION))
    candidate = json.dumps({"digest": str(CANDIDATE), "build_id": "b" * 32}).encode()
    files.write_atomic(root.child("candidate.json"), candidate, mode=RECORD)
    (root.path / "candidate.json").write_bytes(candidate)
    return files


def request(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot | None, *arguments: str,
    environment: dict[str, str] | None = None,
) -> commandspecs.Request:
    return commandspecs.Request(
        arguments=arguments,
        context=contexts.Context(
            settings=loader.load(host_file=None, environment={}),
            repository=safepaths.SourceRoot.adopt(REPOSITORY),
            root=root,
            environment=environment or {},
            bundle=lambda _root: ports,
        ),
    )


def test_readiness_reports_every_check_with_the_recorded_ones_passing(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    files = recorded_store(root, checks=3)
    bundle = dataclasses.replace(ports, files=files)

    reply = readiness_command.run(request(bundle, root))

    assert isinstance(reply.document, dict)
    assert reply.document["counts"] == {"NOT TESTED": 59, "PASS": 3}
    assert reply.document["ready"] is False and reply.document["faults"] == []
    assert reply.exit_code == 0 and reply.narrative == ""


def test_readiness_renders_a_table_when_asked_and_withholds_under_strict(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    files = recorded_store(root, checks=2)
    bundle = dataclasses.replace(ports, files=files)

    reply = readiness_command.run(request(bundle, root, "--table", "--strict"))

    assert reply.document is None and reply.text is not None
    assert reply.text.startswith("store version 2, strict readiness\n")
    assert "PASS 2" in reply.text


@pytest.mark.parametrize("has_root", [False, True])
def test_readiness_is_skipped_without_a_root_or_a_candidate(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot, has_root: bool
) -> None:
    reply = readiness_command.run(request(ports, root if has_root else None))

    assert isinstance(reply.document, dict) and "skipped" in reply.document
    assert reply.exit_code == 0


def test_evidence_verify_chain_replays_an_intact_chain(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    files = recorded_store(root, checks=4)
    bundle = dataclasses.replace(ports, files=files)

    reply = evidence_command.run(request(bundle, root, "verify-chain"))

    assert reply.document == {"entries": 4, "intact": True, "first_break": None}
    assert reply.exit_code == 0


def test_evidence_verify_chain_names_the_first_break(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    files = recorded_store(root, checks=4)
    chain = root.child("attestation/ledger/chain.jsonl")
    lines = files.read_bytes(chain, limit=1 << 20).splitlines()
    lines[1] = lines[1].replace(b'"PASS"', b'"FAIL"')
    files.write_atomic(chain, b"\n".join(lines) + b"\n", mode=RECORD)
    bundle = dataclasses.replace(ports, files=files)

    reply = evidence_command.run(request(bundle, root, "verify-chain"))

    assert isinstance(reply.document, dict) and reply.document["intact"] is False
    assert reply.document["first_break"]["sequence"] == 1  # type: ignore[index]
    assert reply.exit_code == 1 and "broken" in reply.narrative


def test_evidence_without_a_root_is_skipped(ports: portset.HostPorts) -> None:
    reply = evidence_command.run(request(ports, None, "verify-chain"))

    assert isinstance(reply.document, dict) and "skipped" in reply.document
