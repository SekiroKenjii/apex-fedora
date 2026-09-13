"""The operate command reaches the test machine as the account the access directory names."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import guestoperations as ops
import pytest
from mirroredfiles import MirroredFiles
from test_verify_command import running

from apex.cli import commandspecs
from apex.cli.commands import operate_command
from apex.config import defaults, loader
from apex.kernel import errors, refusals, safepaths
from apex.model import machines
from apex.ports import portset
from apex.verification import updateops
from apex.wiring import contexts

REPOSITORY = Path(__file__).resolve().parents[3]
CANDIDATE = "sha256:" + "f" * 64


@pytest.fixture
def root(tmp_path: Path) -> safepaths.RuntimeRoot:
    base = tmp_path / "runtime"
    base.mkdir(mode=0o700)
    (base / defaults.AGENT_WHEEL_NAME).write_bytes(b"wheel")
    (base / "candidate.json").write_text(json.dumps({"digest": CANDIDATE, "build_id": "b" * 32}))
    for name in ("disk.qcow2", "code.fd", "vars.fd"):
        (base / name).write_bytes(b"")
    return safepaths.RuntimeRoot.adopt(base)


def request(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot, *arguments: str
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


def prepared(ports: portset.HostPorts, root: safepaths.RuntimeRoot, answers: dict) -> tuple:
    files = MirroredFiles()
    (root.path / defaults.GUEST_KEY_NAME).write_bytes(b"key")
    ops.exported_fixture(ports, files, root)
    access = ops.access_directory(files, root)
    guest = ops.answering(answers)
    held = dataclasses.replace(
        ops.held(ports, files, guest), hypervisor=ports.hypervisor, monitor=ports.monitor
    )
    running(held, root, machines.VmRole.TEST)
    return held, guest, access


@pytest.mark.parametrize(
    "arguments",
    [
        ("update", "--action", "explode"),
        ("recovery", "--action", "provision"),
        ("update", "--action", "provision", "--inspection", "x.json"),
        ("initramfs", "--action", "inject"),
    ],
)
def test_an_action_the_family_does_not_have_or_a_stray_inspection_is_refused(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot, arguments: tuple[str, ...]
) -> None:
    with pytest.raises(errors.Refusal) as raised:
        operate_command.run(
            request(ports, root, *arguments, "--fixture", "c" * 32, "--access", "a")
        )

    assert raised.value.reason is refusals.RefusalReason.REQUEST_MALFORMED


def test_an_update_operation_runs_as_the_access_directory_s_account_and_names_its_report(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    held, guest, access = prepared(
        ports,
        root,
        {
            "update.state": [ops.state(ops.IMAGE_A), ops.state(ops.IMAGE_A, staged=ops.IMAGE_B)],
            "update.operate": {"returncode": 0},
            "update.sentinel": {"action": "verify", "sha256": updateops.SENTINEL_DIGEST},
        },
    )

    reply = operate_command.run(
        request(
            held,
            root,
            "update",
            "--action",
            "forward",
            "--fixture",
            ops.FIXTURE,
            "--access",
            str(access),
        )
    )

    assert reply.exit_code == 0, reply.narrative
    assert isinstance(reply.document, dict) and reply.document["succeeded"] is True
    assert reply.document["status"] == "PASS"
    report = Path(str(reply.document["report"]))
    assert report.name == "update.json" and json.loads(report.read_bytes())["action"] == "forward"
    assert guest.targets[-1].user == defaults.TEST_ACCOUNT
    assert guest.targets[-1].key.path == access / defaults.TEST_KEY_NAME
    assert guest.passwords == [ops.PASSWORD] * 3
    assert ops.PASSWORD not in json.dumps(reply.document)


def test_a_refused_operation_replies_with_the_refusal_and_keeps_the_report(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    held, _, access = prepared(ports, root, {"recovery.inspect": ops.inspection(ops.IMAGE_B)})

    reply = operate_command.run(
        request(
            held,
            root,
            "recovery",
            "--action",
            "retry-config",
            "--fixture",
            ops.FIXTURE,
            "--access",
            str(access),
        )
    )

    assert reply.exit_code == errors.Refusal.exit_code
    assert isinstance(reply.document, dict)
    assert reply.document["refusal"] == str(refusals.RefusalReason.UPDATE_STATE_UNEXPECTED)
    assert reply.document["status"] is None and reply.document["report"] is None
    assert "recovery:" in reply.narrative


def test_the_older_recipe_names_and_operands_are_kept() -> None:
    assert [(recipe.name, recipe.parameters) for recipe in operate_command.JUST_RECIPES] == [
        ("test-update", ("action", "fixture", "access")),
        ("test-recovery", ("action", "fixture", "access")),
        ("test-initramfs-inspect", ("fixture", "access")),
        ("test-initramfs-inject", ("fixture", "access", "inspection")),
        ("test-initramfs-rescue", ("fixture", "access")),
    ]
    inject = operate_command.JUST_RECIPES[3].argv
    assert inject[:4] == ("operate", "initramfs", "--action", "inject")
    assert inject[-2:] == ("--inspection", "{{inspection}}")
