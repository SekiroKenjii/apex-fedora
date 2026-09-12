"""The fingerprint regression harness, carried verbatim and run as the builder user.

`test-fingerprint.py` drives six upstream fprintd cases and two of this project's over a
virtual device on a private bus. It is the program that produced the recorded result, and it
is not rewritten: the agent writes its bytes beside the sources the host delivered and runs
them as the unprivileged builder, since the harness refuses root. Its report is judged here
the way the older host judged it.
"""

from __future__ import annotations

from importlib import resources

from apex.config import defaults
from apex.kernel import commands, encoding, hashing, identifiers, quantities, safepaths
from apex.ports import files

ASSET = "test-fingerprint.py"
SUFFIX = ".verbatim"
PACKAGE = "apex.assets.verbatim"
EXPECTED_TESTS = 8
PASS = "PASS"
FAIL = "FAIL"
BLOCKED = "BLOCKED"
READABLE = quantities.FileMode(0o644)


def source() -> bytes:
    return resources.files(PACKAGE).joinpath(ASSET + SUFFIX).read_bytes()


def digest() -> identifiers.Digest:
    return hashing.digest_bytes(source())


def place(port: files.FileSystemPort, into: safepaths.SafePath) -> identifiers.Digest:
    """Write the harness where the builder user can read it."""
    return port.write_atomic(into / ASSET, source(), mode=READABLE)


def argv(
    harness: safepaths.SafePath, sources: safepaths.SafePath, output: safepaths.SafePath
) -> commands.Argv:
    return commands.Argv.of(
        "runuser", "-u", defaults.BUILDER_USER, "--",
        "env", "PYTHONDONTWRITEBYTECODE=1", "python3", harness, sources, output,
    )


def judge(report: encoding.Document | None, *, exit_code: int) -> str:
    """The older host's reading: a pass needs every case run, none skipped and a clean exit.

    A failure is the harness's own word. Anything else, including a report that says PASS
    with a case missing, is a run that blocks the verdict rather than one that decides it.
    """
    if report is None:
        return BLOCKED
    status = report.get("status")
    if status == FAIL:
        return FAIL
    complete = report.get("tests_run") == EXPECTED_TESTS and not report.get("skipped")
    if status == PASS and exit_code == 0 and complete:
        return PASS
    return BLOCKED
