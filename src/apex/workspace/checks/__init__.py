"""The checks `apex check` runs, one module each; adding a check is adding a file here.

Each check runs one pinned tool over the trees it holds, or reads the tree itself, and
answers PASS or FAIL with the tail of what it saw. None of them is advisory: the command
exits non-zero when any one fails, and the gate stops there.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Mapping
from pathlib import Path

from apex.config import defaults
from apex.kernel import commands, encoding, safepaths
from apex.ports import files, process
from apex.registry import casebook

DIRECTORY = Path(__file__).resolve().parent
PASS = "PASS"
FAIL = "FAIL"
TAIL_LINES = 40


@dataclasses.dataclass(frozen=True, slots=True)
class Site:
    """Where a check runs: the checkout, the two ports it may use, the interpreter's version."""

    processes: process.ProcessPort
    filesystem: files.FileSystemPort
    repository: Path
    python: str


@dataclasses.dataclass(frozen=True, slots=True)
class Outcome:
    status: str
    detail: str
    returncode: int | None = None

    @property
    def passed(self) -> bool:
        return self.status == PASS

    def document(self) -> encoding.Document:
        return {"status": self.status, "detail": self.detail, "returncode": self.returncode}


Run = Callable[[Site], Outcome]


@dataclasses.dataclass(frozen=True, slots=True)
class Check:
    id: str
    summary: str
    order: int
    run: Run


BOOK: casebook.Casebook[Check] = casebook.Casebook(
    kind="check", namespace=__name__, key=lambda check: check.id, known="the checks are"
)


def declare(check: Check) -> Check:
    return BOOK.declare(check)


def registered() -> tuple[Check, ...]:
    return tuple(sorted(BOOK.registered(), key=lambda check: (check.order, check.id)))


def lookup(name: str) -> Check:
    return BOOK.lookup(name)


def tail(text: str) -> str:
    lines = text.rstrip("\n").splitlines()
    return "\n".join(lines[-TAIL_LINES:])


def program(
    site: Site, argv: tuple[str, ...], *, variables: Mapping[str, str] | None = None
) -> Outcome:
    """One tool run in the checkout; its exit code is the verdict, its last lines the detail."""
    completed = site.processes.run(
        commands.Argv.of(*argv),
        deadline=defaults.CHECK_DEADLINE,
        limit=commands.OutputLimit(defaults.CHECK_OUTPUT_LIMIT.value),
        cwd=safepaths.SafePath(site.repository),
        variables=variables,
    )
    text = completed.stdout.decode(errors="replace") + completed.stderr.decode(errors="replace")
    return Outcome(
        status=PASS if completed.succeeded else FAIL,
        detail=tail(text),
        returncode=completed.exit_code,
    )
