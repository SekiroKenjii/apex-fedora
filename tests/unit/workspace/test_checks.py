"""The checks: one per module, in their order, each a pinned tool or a reading of the tree."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from apex.adapters.fakes import fake_files, fake_process
from apex.adapters.real import real_process
from apex.config import budgets, toolchain
from apex.kernel import errors, refusals
from apex.workspace import checks
from apex.workspace.checks import sizes_check, tree_check

REPOSITORY = Path(__file__).resolve().parents[3]
ORDERED = (
    "format",
    "lint",
    "types",
    "pyright",
    "deadcode",
    "duplicates",
    "imports",
    "architecture",
    "tree",
    "sizes",
)


class Replying(fake_process.ScriptedProcess):
    """Answers every argument vector with the exit code the test declares."""

    def __init__(self, failing: frozenset[str] = frozenset()) -> None:
        super().__init__()
        self.failing = failing
        self.stdin_seen: list[bytes | None] = []

    def run(self, argv: Any, **keywords: Any) -> Any:
        vector = tuple(str(item) for item in argv)
        failing = any(word in self.failing for word in vector)
        self.expect(
            vector,
            fake_process.Reply(
                exit_code=1 if failing else 0,
                stdout=b"line one\nline two\n",
                stderr=b"boom\n" if failing else b"",
            ),
        )
        return super().run(argv, **keywords)


def site(processes: fake_process.ScriptedProcess) -> checks.Site:
    return checks.Site(
        processes=processes,
        filesystem=fake_files.MemoryFiles(),
        repository=REPOSITORY,
        python="3.14.4",
    )


def test_every_check_module_declares_one_check_and_the_order_is_the_declared_one() -> None:
    modules = sorted(p for p in checks.DIRECTORY.glob("*_check.py"))

    assert len(checks.registered()) == len(modules)
    assert tuple(check.id for check in checks.registered()) == ORDERED
    assert all(check.summary for check in checks.registered())
    with pytest.raises(errors.Refusal) as raised:
        checks.lookup("spelling")
    assert raised.value.reason is refusals.RefusalReason.UNIT_UNKNOWN


def test_a_program_check_runs_in_the_checkout_and_answers_with_the_exit_code() -> None:
    process = Replying(frozenset({"mypy"}))
    held = site(process)

    passed = checks.lookup("lint").run(held)
    failed = checks.lookup("types").run(held)

    assert passed.passed and passed.returncode == 0
    assert not failed.passed and failed.returncode == 1 and "boom" in failed.detail
    assert all(str(cwd) == str(REPOSITORY) for cwd in process.directories)
    lint = tuple(process.calls[0])
    assert lint[:5] == ("uv", "run", "--no-project", "--python", "3.14.4")
    assert toolchain.pin("ruff") in lint and "check" in lint


@pytest.mark.parametrize(
    "name,tool,word",
    [
        ("format", "ruff", "--check"),
        ("types", "mypy", "--strict"),
        ("pyright", "pyright", "sh"),
        ("deadcode", "vulture", "--min-confidence"),
        ("duplicates", "pylint", "--enable=R0801"),
        ("imports", "import-linter", "lint-imports"),
        ("architecture", "pytest", toolchain.ARCHITECTURE_TESTS),
    ],
)
def test_each_tool_check_names_its_pinned_tool_and_its_mode(
    name: str, tool: str, word: str
) -> None:
    process = Replying()

    found = checks.lookup(name).run(site(process))

    assert found.passed
    argv = tuple(process.calls[-1])
    assert toolchain.pin(tool) in argv and word in argv


def test_the_import_check_puts_the_package_on_the_path() -> None:
    process = Replying()

    checks.lookup("imports").run(site(process))

    assert process.variables[-1] == {"PYTHONPATH": "src"}


def test_the_size_table_names_an_oversize_module_and_a_package_over_budget(tmp_path: Path) -> None:
    package = tmp_path / "src" / "apex"
    (package / "kernel").mkdir(parents=True)
    (package / "kernel" / "big.py").write_text("x = 1\n" * (budgets.MODULE_LINE_LIMIT + 1))
    (package / "kernel" / "small.py").write_text("y = 2\n")
    (package / "unknown").mkdir()
    (package / "unknown" / "thing.py").write_text("z = 3\n")

    totals, oversize = sizes_check.measure(package)

    assert totals == {"kernel": budgets.MODULE_LINE_LIMIT + 2, "unknown": 1}
    assert oversize == [f"kernel/big.py: {budgets.MODULE_LINE_LIMIT + 1} lines"]


def test_the_size_check_passes_over_the_real_package_and_prints_the_table() -> None:
    found = checks.lookup("sizes").run(site(Replying()))

    assert found.passed, found.detail
    assert found.detail.splitlines()[0].startswith("package")
    assert any(line.startswith("kernel") for line in found.detail.splitlines())


def repository_with(tmp_path: Path, name: str, payload: bytes) -> Path:
    root = tmp_path / "repo"
    root.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    (root / name).write_bytes(payload)
    subprocess.run(["git", "-C", str(root), "add", name], check=True)
    return root


def test_the_tree_check_judges_every_tracked_file_by_the_repository_rules(tmp_path: Path) -> None:
    clean = repository_with(tmp_path / "a", "README.md", b"# Apex\n")
    tainted = repository_with(tmp_path / "b", "notes.md", b"<!-- apex-" + b"local-only -->\n")
    processes = real_process.SubprocessRunner()

    passed = tree_check.run(
        checks.Site(
            processes=processes,
            filesystem=fake_files.MemoryFiles(),
            repository=clean,
            python="3.14.4",
        )
    )
    failed = tree_check.run(
        checks.Site(
            processes=processes,
            filesystem=fake_files.MemoryFiles(),
            repository=tainted,
            python="3.14.4",
        )
    )

    assert passed.passed and "1 tracked entries" in passed.detail
    assert not failed.passed and "repository.local-only-content" in failed.detail
