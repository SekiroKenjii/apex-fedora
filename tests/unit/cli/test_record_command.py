"""A result recorded by hand goes through the minting rules with the operator's note as proof."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pretendingreal import pretending_real

from apex.attestation import reading
from apex.cli import commandspecs
from apex.cli.commands import record_command
from apex.config import loader
from apex.kernel import errors, quantities, refusals, safepaths
from apex.model import storemark
from apex.ports import portset
from apex.wiring import contexts

REPOSITORY = Path(__file__).resolve().parents[3]
CANDIDATE = "sha256:" + "c" * 64


@pytest.fixture
def root(tmp_path: Path) -> safepaths.RuntimeRoot:
    base = tmp_path / "runtime"
    base.mkdir(mode=0o700)
    (base / "candidate.json").write_text(json.dumps({"digest": CANDIDATE, "build_id": "b" * 32}))
    return safepaths.RuntimeRoot.adopt(base)


def proof(ports: portset.HostPorts, tmp_path: Path, name: str = "summary.json") -> Path:
    path = tmp_path / name
    path.write_bytes(b'{"boots": 10}')
    ports.files.write_atomic(
        safepaths.SafePath(path), path.read_bytes(), mode=quantities.FileMode(0o600)
    )
    return path


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


def test_a_pass_with_proof_is_minted_with_the_note_filed_first(
    root: safepaths.RuntimeRoot, tmp_path: Path
) -> None:
    ports = pretending_real()
    cited = proof(ports, tmp_path)

    reply = record_command.run(
        request(
            ports,
            root,
            "boot.ten-cycles",
            "PASS",
            "--environment",
            "vm",
            "--description",
            "Ten offline boots",
            "--proof",
            str(cited),
            "--reason",
            "normal boots",
        )
    )

    assert isinstance(reply.document, dict)
    recorded = reply.document["recorded"]
    assert isinstance(recorded, dict)
    assert recorded["check"] == "boot.ten-cycles" and recorded["verdict"] == "PASS"
    assert isinstance(recorded["proofs"], list) and len(recorded["proofs"]) == 2
    (root.path / storemark.MARK_NAME).write_bytes(storemark.document(storemark.SECOND_VERSION))
    found = reading.read_store(root.path, files=ports.files)
    assert [str(item.check) for item in found.records] == ["boot.ten-cycles"]
    assert found.candidate is not None and str(found.candidate) == CANDIDATE


def test_a_hardware_result_from_a_machine_is_refused(
    root: safepaths.RuntimeRoot, tmp_path: Path
) -> None:
    ports = pretending_real()
    cited = proof(ports, tmp_path)

    with pytest.raises(errors.Refusal) as raised:
        record_command.run(
            request(
                ports,
                root,
                "audio.speakers",
                "PASS",
                "--environment",
                "vm",
                "--description",
                "d",
                "--proof",
                str(cited),
            )
        )

    assert raised.value.reason is refusals.RefusalReason.HARDWARE_REQUIRES_PHYSICAL


def test_a_pass_needs_a_proof_beyond_the_note(root: safepaths.RuntimeRoot) -> None:
    ports = pretending_real()

    with pytest.raises(errors.Refusal) as raised:
        record_command.run(
            request(
                ports, root, "boot.ten-cycles", "PASS", "--environment", "vm", "--description", "d"
            )
        )

    assert raised.value.reason is refusals.RefusalReason.PASS_REQUIRES_PROOF


def test_an_unknown_check_is_refused(root: safepaths.RuntimeRoot) -> None:
    with pytest.raises(errors.Refusal) as raised:
        record_command.run(
            request(
                pretending_real(),
                root,
                "no.such.check",
                "BLOCKED",
                "--environment",
                "vm",
                "--description",
                "d",
            )
        )

    assert raised.value.reason is refusals.RefusalReason.UNKNOWN_CHECK


def test_without_a_candidate_nothing_is_recorded(tmp_path: Path) -> None:
    base = tmp_path / "empty"
    base.mkdir(mode=0o700)

    with pytest.raises(errors.PreconditionUnmet):
        record_command.run(
            request(
                pretending_real(),
                safepaths.RuntimeRoot.adopt(base),
                "boot.ten-cycles",
                "BLOCKED",
                "--environment",
                "vm",
                "--description",
                "d",
            )
        )
