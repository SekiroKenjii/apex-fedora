"""A verified image build becomes the candidate; the previous one is kept, never approved."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from parentbuild import documents
from signedbundle import BUILD, keys, real_files_bundle, signed_output

from apex.cli import commandspecs
from apex.cli.commands import candidate_command
from apex.config import loader
from apex.kernel import errors, identifiers, refusals, safepaths
from apex.ports import portset
from apex.wiring import contexts

REPOSITORY = Path(__file__).resolve().parents[3]
OTHER = identifiers.BuildId("f" * 32)


@pytest.fixture
def root(tmp_path: Path) -> safepaths.RuntimeRoot:
    base = tmp_path / "runtime"
    base.mkdir(mode=0o700)
    return safepaths.RuntimeRoot.adopt(base)


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


def completed(
    ports: portset.HostPorts,
    root: safepaths.RuntimeRoot,
    private: Path,
    build: identifiers.BuildId = BUILD,
    *,
    status: str = "PASS",
    image_id: str = "b" * 64,
) -> identifiers.Digest:
    digest = documents(ports.files, root, build, status=status, image_id=image_id)
    output = root.path / "exports" / str(build) / "output"
    signed_output(
        ports,
        root,
        private,
        build=build,
        digest=str(digest),
        extra={
            "image.json": (output / "image.json").read_bytes(),
            "manifest.json": (output / "manifest.json").read_bytes(),
        },
    )
    return digest


def test_a_completed_verified_image_build_is_selected_for_testing(
    root: safepaths.RuntimeRoot,
) -> None:
    ports = real_files_bundle()
    private, public = keys(ports, root)
    digest = completed(ports, root, private)

    reply = candidate_command.run(
        request(ports, root, "select", "--build", str(BUILD), "--key", str(public))
    )

    assert reply.document == {
        "selected": {"digest": str(digest), "build_id": str(BUILD)},
        "previous": None,
        "archived": None,
        "note": "Candidate selected for testing, not approved for installation",
    }
    written = json.loads((root.path / "candidate.json").read_bytes())
    assert written["digest"] == str(digest) and written["build_id"] == str(BUILD)
    assert written["verification"]["status"] == "PASS"
    assert (root.path / "candidate.json").stat().st_mode & 0o777 == 0o600


def test_selecting_another_build_archives_the_previous_candidate_under_its_run(
    root: safepaths.RuntimeRoot,
) -> None:
    ports = real_files_bundle()
    private, public = keys(ports, root)
    first = completed(ports, root, private)
    candidate_command.run(
        request(ports, root, "select", "--build", str(BUILD), "--key", str(public))
    )
    second = completed(ports, root, private, OTHER, image_id="a" * 64)

    reply = candidate_command.run(
        request(ports, root, "select", "--build", str(OTHER), "--key", str(public))
    )

    assert isinstance(reply.document, dict)
    assert reply.document["previous"] == str(first)
    archived = Path(str(reply.document["archived"]))
    assert archived.parent.parent == root.path / "candidate-history"
    assert json.loads(archived.read_bytes())["digest"] == str(first)
    assert json.loads((root.path / "candidate.json").read_bytes())["digest"] == str(second)


def test_selecting_the_same_build_again_archives_nothing(root: safepaths.RuntimeRoot) -> None:
    ports = real_files_bundle()
    private, public = keys(ports, root)
    completed(ports, root, private)
    candidate_command.run(
        request(ports, root, "select", "--build", str(BUILD), "--key", str(public))
    )

    reply = candidate_command.run(
        request(ports, root, "select", "--build", str(BUILD), "--key", str(public))
    )

    assert isinstance(reply.document, dict) and reply.document["archived"] is None
    assert not (root.path / "candidate-history").exists()


def test_a_build_that_did_not_pass_is_refused_before_the_signature_is_read(
    root: safepaths.RuntimeRoot,
) -> None:
    ports = real_files_bundle()
    private, public = keys(ports, root)
    completed(ports, root, private, status="FAIL")

    with pytest.raises(errors.Refusal) as raised:
        candidate_command.run(
            request(ports, root, "select", "--build", str(BUILD), "--key", str(public))
        )

    assert raised.value.reason is refusals.RefusalReason.BUILD_PARENT_NOT_COMPLETE
    assert not (root.path / "candidate.json").exists()


def test_a_build_with_no_record_is_refused(root: safepaths.RuntimeRoot) -> None:
    ports = real_files_bundle()
    _, public = keys(ports, root)

    with pytest.raises(errors.Refusal) as raised:
        candidate_command.run(
            request(ports, root, "select", "--build", str(BUILD), "--key", str(public))
        )

    assert raised.value.reason is refusals.RefusalReason.BUILD_PARENT_NOT_COMPLETE
