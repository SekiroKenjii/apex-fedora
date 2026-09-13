"""The harness wrapper carries the asset's bytes and reads its report as the older host did."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from apex.adapters.fakes import fake_files
from apex.agent import fingerprintharness
from apex.kernel import encoding, safepaths

REPOSITORY = Path(__file__).resolve().parents[3]
WORK = safepaths.SafePath(Path("/var/tmp/apex-fingerprint-" + "a" * 32))


def report(**changes: encoding.JsonValue) -> dict[str, encoding.JsonValue]:
    document: dict[str, encoding.JsonValue] = {
        "status": "PASS", "tests_run": 8, "skipped": [], "failures": [], "errors": [],
    }
    document.update(changes)
    return document


def test_the_harness_is_the_verbatim_asset_byte_for_byte() -> None:
    older = (
        REPOSITORY / "src" / "apex" / "assets" / "verbatim" / f"{fingerprintharness.ASSET}.verbatim"
    ).read_bytes()

    assert fingerprintharness.source() == older
    assert fingerprintharness.digest().hex == hashlib.sha256(older).hexdigest()


def test_the_harness_is_placed_where_the_builder_user_can_read_it() -> None:
    files = fake_files.MemoryFiles()

    placed = fingerprintharness.place(files, WORK)

    path = WORK / fingerprintharness.ASSET
    assert files.read_bytes(path, limit=1 << 20) == fingerprintharness.source()
    assert files.mode_of(path).value == 0o644
    assert placed == fingerprintharness.digest()


def test_the_harness_runs_as_the_builder_user_without_bytecode() -> None:
    argv = fingerprintharness.argv(
        WORK / "test-fingerprint.py", WORK / "fingerprint-sources", WORK / "output"
    )

    assert list(argv) == [
        "runuser", "-u", "builder", "--", "env", "PYTHONDONTWRITEBYTECODE=1", "python3",
        f"{WORK}/test-fingerprint.py", f"{WORK}/fingerprint-sources", f"{WORK}/output",
    ]


@pytest.mark.parametrize(
    "document,exit_code,expected",
    [
        (report(), 0, "PASS"),
        (report(status="FAIL", failures=[["case", "trace"]]), 1, "FAIL"),
        (report(status="BLOCKED", tests_run=7), 1, "BLOCKED"),
        (report(skipped=[["case", "no virtual device"]]), 0, "BLOCKED"),
        (report(tests_run=7), 0, "BLOCKED"),
        (report(), 1, "BLOCKED"),
        ({"status": "OK"}, 0, "BLOCKED"),
        (None, 1, "BLOCKED"),
    ],
)
def test_the_report_is_judged_as_the_older_host_judged_it(
    document: dict[str, encoding.JsonValue] | None, exit_code: int, expected: str
) -> None:
    assert fingerprintharness.judge(document, exit_code=exit_code) == expected
