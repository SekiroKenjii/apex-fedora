"""The patch command runs one reviewed check and replies with where its results were kept."""

from __future__ import annotations

from pathlib import Path

import pytest

from apex.cli import commandspecs
from apex.cli.commands import patch_command
from apex.config import loader
from apex.kernel import errors, refusals, safepaths
from apex.ports import portset
from apex.verification import dialogcheck, elancheck, patchbench
from apex.wiring import contexts

REPOSITORY = Path(__file__).resolve().parents[3]


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


@pytest.fixture
def root(tmp_path: Path) -> safepaths.RuntimeRoot:
    base = tmp_path / "runtime"
    base.mkdir(mode=0o700)
    return safepaths.RuntimeRoot.adopt(base)


@pytest.mark.parametrize(
    "action,module", [("fingerprint-dialog", dialogcheck), ("elan-diagnostics", elancheck)]
)
def test_each_action_runs_its_check_and_replies_with_the_report(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot, monkeypatch: pytest.MonkeyPatch,
    action: str, module: object,
) -> None:
    seen: list[Path] = []

    def check(held: object, held_root: object, repository: object, source: Path) -> object:
        seen.append(source)
        return patchbench.Checked(
            document={"status": "PASS", "cases": {"a": {}, "b": {}}},
            proof=root.child("results.json"),
        )

    monkeypatch.setattr(module, "check", check)

    reply = patch_command.run(request(ports, root, action, "--source", "/tmp/x.c"))

    assert reply.exit_code == 0
    assert reply.document == {
        "status": "PASS", "cases": 2, "report": str(root.path / "results.json"),
    }
    assert seen == [Path("/tmp/x.c")]


def test_without_a_root_the_check_has_nowhere_to_keep_results(ports: portset.HostPorts) -> None:
    with pytest.raises(errors.PreconditionUnmet) as raised:
        patch_command.run(request(ports, None, "fingerprint-dialog", "--source", "/tmp/x.c"))

    assert raised.value.reason is refusals.RefusalReason.PATH_NOT_A_DIRECTORY


def test_an_unknown_action_or_a_missing_source_stops_at_the_parser(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    with pytest.raises(SystemExit):
        patch_command.run(request(ports, root, "kernel"))
    with pytest.raises(SystemExit):
        patch_command.run(request(ports, root, "elan-diagnostics"))


def test_the_recipes_keep_the_older_names_and_operands() -> None:
    assert [(item.name, item.parameters) for item in patch_command.RECIPES] == [
        ("test-fingerprint-dialog", ("source",)),
        ("test-elan-diagnostics", ("source",)),
    ]
