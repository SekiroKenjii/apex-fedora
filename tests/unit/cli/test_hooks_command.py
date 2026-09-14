"""The hooks command writes three hooks of three lines and refuses to write over anything else."""

from __future__ import annotations

from pathlib import Path

import pytest

from apex.adapters.fakes import fake_files, fake_process
from apex.cli import commandspecs, hookinstall
from apex.cli.commands import hooks_command
from apex.config import defaults, loader
from apex.kernel import errors, quantities, refusals, safepaths
from apex.wiring import contexts

REPOSITORY = Path(__file__).resolve().parents[3]
HOOKS = REPOSITORY / ".git" / "hooks"


def git(*arguments: str) -> tuple[str, ...]:
    return ("git", "-C", str(REPOSITORY), *arguments)


def scripted() -> fake_process.ScriptedProcess:
    return fake_process.ScriptedProcess(
        {git("rev-parse", "--git-path", "hooks"): fake_process.Reply(stdout=b".git/hooks\n")}
    )


def context(
    processes: fake_process.ScriptedProcess, filesystem: fake_files.MemoryFiles
) -> contexts.Context:
    return contexts.Context(
        settings=loader.load(host_file=None, environment={}),
        repository=safepaths.SourceRoot.adopt(REPOSITORY),
        root=None,
        environment={},
        bundle=lambda _root: pytest.fail("never asked"),
        processes=processes,
        filesystem=filesystem,
    )


def test_three_hooks_are_written_executable_each_naming_its_own_kind() -> None:
    filesystem = fake_files.MemoryFiles()
    filesystem.make_directory(safepaths.SafePath(HOOKS), mode=quantities.FileMode(0o755))

    reply = hooks_command.run(
        commandspecs.Request(arguments=(), context=context(scripted(), filesystem))
    )

    assert reply.exit_code == 0 and reply.narrative == "Local Git hooks installed\n"
    assert isinstance(reply.document, dict)
    assert reply.document["installed"] == [
        str(HOOKS / name) for name in ("commit-msg", "pre-commit", "pre-push")
    ]
    for name in ("commit-msg", "pre-commit", "pre-push"):
        target = safepaths.SafePath(HOOKS / name)
        body = filesystem.read_bytes(target, limit=1 << 16).decode()
        assert body == hookinstall.body(name)
        assert body.splitlines() == [
            "#!/bin/sh",
            defaults.HOOK_MARKER,
            f'exec {hookinstall.ENTRY} git-hook {name} "$@"',
        ]
        assert filesystem.mode_of(target) == defaults.HOOK_MODE
    assert "uv run --no-project --python" in hookinstall.ENTRY


def test_a_hook_that_is_not_ours_and_no_repository_are_refused() -> None:
    filesystem = fake_files.MemoryFiles()
    filesystem.make_directory(safepaths.SafePath(HOOKS), mode=quantities.FileMode(0o755))
    filesystem.write_atomic(
        safepaths.SafePath(HOOKS / "pre-push"), b"#!/bin/sh\necho mine\n", mode=defaults.HOOK_MODE
    )

    with pytest.raises(errors.Refusal) as foreign:
        hooks_command.run(
            commandspecs.Request(arguments=(), context=context(scripted(), filesystem))
        )
    with pytest.raises(errors.Refusal) as absent:
        hooks_command.run(
            commandspecs.Request(
                arguments=(), context=context(scripted(), fake_files.MemoryFiles())
            )
        )

    assert foreign.value.reason is refusals.RefusalReason.HOOK_FOREIGN
    assert absent.value.reason is refusals.RefusalReason.HOOK_NO_REPOSITORY
    kept = filesystem.read_bytes(safepaths.SafePath(HOOKS / "pre-push"), limit=1 << 16)
    assert kept == b"#!/bin/sh\necho mine\n"
    assert not filesystem.exists(safepaths.SafePath(HOOKS / "commit-msg"))
