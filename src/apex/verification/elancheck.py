"""The ELAN status diagnostic's helpers, applied to the reviewed driver and run on fake transfers.

The patch must apply under git's index check and under patch without fuzz; the helpers it
adds are cut out between their markers and built into a harness with fake transfer and
device objects; twenty scenarios prove the opt-in and identity guards stay silent, the
excluded transfers log nothing, the four status values and the event budget are reported
in the fixed metadata format, and no synthetic payload marker reaches the output. The
patch is then reversed and the source must hash to what the lock reviewed.
"""

from __future__ import annotations

import re
from pathlib import Path

from apex.config import defaults
from apex.kernel import encoding, errors, refusals, safepaths
from apex.ports import portset
from apex.verification import patchbench

PASS = "PASS"
NOT_TESTED = "NOT TESTED"
HELPERS_MARKER = "/* APEX_DIAGNOSTIC_HELPERS */"
HELPERS_START = "/* This opt-in diagnostic never prints"
HELPERS_END = "static void\nelan_cmd_done ("
SOURCE_PATH = "libfprint/drivers/elan.c"
CHECK = "elan-diagnostics"
SILENT = (
    "disabled",
    "wrong-opt-in",
    "debug-transfer",
    "debug-messages",
    "wrong-device",
    "wrong-vendor",
)
EXCLUDED = (
    "image",
    "other-command",
    "wrong-endpoint",
    "outgoing",
    "zero",
    "overlong",
    "wrong-expected",
    "null-buffer",
    "failed",
)
STATUS = ("status-0", "status-85", "status-175", "status-255")
BUDGET = "budget"
BUDGET_LINES = 16
NO_STATUS = -1
SENTINEL = "PRIVATE_PAYLOAD_SENTINEL"
LINE = re.compile(
    r"apex-elan-v1 event=(probe|transfer-error) action=3 state=2 "
    r"command=(pre-scan|image|other) expected=-?\d+ actual=-?\d+ "
    r"status=(-?\d+) domain=[0-4] code=-?\d+"
)
QUIETED = ("-Wno-unused-parameter",)
SCOPE = "extracted metadata helpers with synthetic transfers and invalid non-status buffers"
EXPECTED_TEXTS = (
    ("apex_elan_trace_transfer (transfer, dev, error);", 1),
    ('apex_elan_emit (dev, ssm, "pre-scan-protocol", 1,', 1),
)


def _failed(expected: str, observed: str) -> errors.VerificationFailed:
    return errors.VerificationFailed(check=CHECK, expected=expected, observed=observed)


def helpers_of(content: str) -> str:
    """The helper block the patch adds, from its leading remark to the callback it precedes."""
    start = content.find(HELPERS_START)
    end = content.find(HELPERS_END, max(start, 0))
    if start < 0 or end < 0:
        raise errors.Refusal(
            refusals.RefusalReason.PATCH_SOURCE_UNEXPECTED,
            subject="the patched driver holds no diagnostic helper block",
        )
    return content[start:end]


def require_bounded(content: str, helpers: str) -> None:
    reads = helpers.count("transfer->buffer[0]")
    if reads != 1:
        raise _failed("one status byte read in the helpers", str(reads))
    if "error->message" in helpers:
        raise _failed("no error message body in the helpers", "error->message")
    for text, times in EXPECTED_TEXTS:
        if content.count(text) != times:
            raise _failed(f"{text!r} {times} time", str(content.count(text)))


def judge_case(case: str, lines: list[str], output: str) -> None:
    """A silent case prints nothing; every other prints the fixed format with its status."""
    if case in SILENT:
        if lines:
            raise _failed(f"{case}: no output", f"{len(lines)} lines")
        return
    expected = BUDGET_LINES if case == BUDGET else 1
    if len(lines) != expected:
        raise _failed(f"{case}: {expected} lines", str(len(lines)))
    matched = [LINE.fullmatch(line) for line in lines]
    if any(item is None for item in matched):
        raise _failed(f"{case}: the fixed metadata format", "a line that differs")
    if SENTINEL in output:
        raise _failed(f"{case}: no payload in the output", SENTINEL)
    status = int(case[len("status-") :]) if case in STATUS else NO_STATUS
    if any(item is not None and int(item[3]) != status for item in matched):
        raise _failed(f"{case}: status {status}", "another status")


def check(
    ports: portset.HostPorts,
    root: safepaths.RuntimeRoot,
    repository: safepaths.SourceRoot,
    source: Path,
) -> patchbench.Checked:
    patchbench.require_not_root()
    bench = patchbench.open_bench(
        ports,
        root,
        repository,
        directory_name=defaults.ELAN_TESTS_DIRECTORY,
        lock_path=defaults.ELAN_LOCK_PATH,
        entries_key="sources",
        source=source,
    )
    target = bench.work / SOURCE_PATH
    patchbench.write(ports, target, patchbench.text(ports, bench.source.path))
    patchbench.run(ports, bench.work, "git", "init", "-q")
    patchbench.run(ports, bench.work, "git", "add", "--", SOURCE_PATH)
    patchbench.run(ports, bench.work, "git", "apply", "--check", "--index", "-p1", str(bench.patch))
    patchbench.apply_patch(ports, bench)
    content = patchbench.text(ports, target.path)
    helpers = helpers_of(content)
    require_bounded(content, helpers)
    program = bench.work / "harness.c"
    harness = patchbench.text(ports, repository.path / defaults.ELAN_HARNESS_PATH)
    patchbench.write(ports, program, harness.replace(HELPERS_MARKER, helpers))
    binary = bench.work / "harness"
    patchbench.compile_program(ports, bench, program, binary, *QUIETED)
    results: dict[str, encoding.JsonValue] = {}
    for case in (*SILENT, *EXCLUDED, *STATUS, BUDGET):
        output = patchbench.case_output(ports, bench, binary, case)
        lines = output.splitlines()
        judge_case(case, lines, output)
        results[case] = {"status": PASS, "lines": lines}
    patchbench.apply_patch(ports, bench, reverse=True)
    ports.digests.forget()
    if ports.digests.file(target) != bench.source_digest:
        raise _failed("the reviewed source restored by the reverse patch", "another digest")
    found: encoding.Document = {
        "status": PASS,
        "scope": SCOPE,
        "source": bench.source_label,
        "source_sha256": bench.source_digest.hex,
        "patch_sha256": bench.patch_digest.hex,
        **patchbench.environment(ports, bench),
        "cases": results,
        "reverse_patch": PASS,
        "git_apply_index_check": PASS,
        "full_driver_build": NOT_TESTED,
        "capture_state_machine": NOT_TESTED,
        "physical_sensor": NOT_TESTED,
    }
    return patchbench.Checked(document=found, proof=patchbench.report(ports, bench, found))
