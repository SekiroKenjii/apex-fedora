"""GNOME's fingerprint dialog handlers, extracted and compiled against device-free shims.

Six handlers are cut out of the reviewed dialog source, unpatched and patched, and built
into the harness with the dialog's own state enumeration and real GLib cancellation. Twelve
scenarios drive them; the unpatched build must reproduce the cleanup and repeated-cancel
defects and the patched build must keep Stop and Release, the cancellation guard, the
daemon-loss path and the pending close, or the check fails naming the first expectation
that did not hold. No sensor, no bus and no GTK object takes part.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from pathlib import Path

from apex.config import defaults
from apex.kernel import encoding, errors, refusals, safepaths
from apex.ports import portset
from apex.verification import patchbench

PASS = "PASS"
NOT_TESTED = "NOT TESTED"
HANDLER_ONLY = "HANDLER ONLY"
STATE_MARKER = "/* APEX_DIALOG_STATE */"
HANDLERS_MARKER = "/* APEX_EXTRACTED_HANDLERS */"
FUNCTION_HEAD = "\nstatic void\n"
DIALOG_STATE = re.compile(r"typedef enum \{[^}]+\} DialogState;")
SOURCE_PATH = "panels/system/users/cc-fingerprint-dialog.c"
HANDLERS = (
    "handle_enroll_signal",
    "enroll_stop_cb",
    "enroll_stop",
    "on_device_owner_changed",
    "cancel_button_clicked_cb",
    "cc_fingerprint_dialog_close_attempt",
)
CASES = (
    "disconnect",
    "cancel",
    "retry",
    "complete",
    "unknown-error",
    "unclaimed",
    "daemon-gone",
    "daemon-present",
    "stop-success",
    "stop-error",
    "cancel-twice",
    "close-pending",
)
SIGNAL_CASES = ("disconnect", "cancel", "retry", "complete", "unknown-error")
CALLBACK_CASES = ("stop-success", "stop-error", "cancel-twice")
CLAIMED_ENROLLING = 68
CLAIMED = 4
STOPPING_ENROLLING = 196
QUIETED = ("-Wno-unused-parameter", "-Wno-unused-function")
SCOPE = "extracted GNOME handlers with stubbed widgets and D-Bus calls"
ASYNC_SCOPE = (
    "Controlled callback ordering with real GCancellable; no D-Bus, GTK object lifetime or "
    "threaded race test"
)
Results = Mapping[str, Mapping[str, encoding.JsonValue]]
Rule = Callable[[Results, Results], bool]


def function(source: str, name: str) -> str:
    """One handler's text from its head to its closing brace, refused unless it appears once."""
    marker = f"{FUNCTION_HEAD}{name} ("
    if source.count(marker) != 1:
        raise errors.Refusal(
            refusals.RefusalReason.PATCH_SOURCE_UNEXPECTED,
            subject=f"{name} does not appear exactly once",
        )
    start = source.index(marker)
    end = source.index("{", start) + 1
    level = 1
    while level:
        level += {"{": 1, "}": -1}.get(source[end], 0)
        end += 1
    return source[start:end]


def _count(cases: Results, case: str, key: str) -> int:
    value = cases[case].get(key)
    return value if isinstance(value, int) else -1


def _flag(cases: Results, case: str, key: str) -> bool:
    return cases[case].get(key) is True


def _cleanup_kept(_before: Results, after: Results) -> bool:
    return all(
        _count(after, case, "state_after_signal") == CLAIMED_ENROLLING
        and _count(after, case, "stop_calls") == 1
        and _count(after, case, "release_calls") == 1
        for case in SIGNAL_CASES
    )


def _callbacks_settled(_before: Results, after: Results) -> bool:
    return all(
        _count(after, case, "state_after_callback") == CLAIMED
        and _count(after, case, "stop_calls") == 0
        and _count(after, case, "release_calls") == 1
        for case in CALLBACK_CASES
    )


RULES: tuple[tuple[str, Rule], ...] = (
    (
        "Pinned source no longer reproduces the cleanup regression",
        lambda before, _: _count(before, "disconnect", "release_calls") == 0
        and _count(before, "cancel", "cancel_calls") == 0,
    ),
    ("Patched handler lost Stop/Release cleanup", _cleanup_kept),
    (
        "Patched cancellation/unclaimed guard regression",
        lambda _, after: _count(after, "cancel", "cancel_calls") == 1
        and _count(after, "unclaimed", "release_calls") == 0,
    ),
    (
        "Daemon-loss path attempted stale cleanup or skipped reacquisition",
        lambda _, after: _count(after, "daemon-gone", "claim_calls") == 1
        and _count(after, "daemon-gone", "release_calls") == 0,
    ),
    (
        "Present owner incorrectly treated as lost",
        lambda _, after: _count(after, "daemon-present", "claim_calls") == 0
        and _count(after, "daemon-present", "release_calls") == 1,
    ),
    ("Stop callback left stale enrollment state", _callbacks_settled),
    (
        "Repeated-cancel regression was not reproduced and fixed",
        lambda before, after: _count(before, "cancel-twice", "state_after_callback")
        == STOPPING_ENROLLING
        and not _flag(after, "cancel-twice", "cancelled_callback"),
    ),
    (
        "Close did not cancel its pending callback and release",
        lambda _, after: _flag(after, "close-pending", "cancelled_callback")
        and _count(after, "close-pending", "release_calls") == 1,
    ),
)


def judge(results: Mapping[str, Results]) -> None:
    before, after = results["unpatched"], results["patched"]
    for expectation, holds in RULES:
        if not holds(before, after):
            raise errors.VerificationFailed(
                check="fingerprint-dialog", expected=expectation, observed="the harness did not"
            )


def _variant(
    ports: portset.HostPorts,
    bench: patchbench.Bench,
    name: str,
    content: str,
    template: str,
    enum: str,
) -> Results:
    program = bench.work / f"{name}.c"
    extracted = "\n".join(function(content, handler) for handler in HANDLERS)
    patchbench.write(
        ports, program, template.replace(STATE_MARKER, enum).replace(HANDLERS_MARKER, extracted)
    )
    binary = bench.work / name
    patchbench.compile_program(ports, bench, program, binary, *QUIETED)
    return {
        case: encoding.parse_object(patchbench.case_output(ports, bench, binary, case).encode())
        for case in CASES
    }


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
        directory_name=defaults.DIALOG_TESTS_DIRECTORY,
        lock_path=defaults.DIALOG_LOCK_PATH,
        entries_key="reviewed_sources",
        source=source,
    )
    template = patchbench.text(ports, repository.path / defaults.DIALOG_HARNESS_PATH)
    content = patchbench.text(ports, bench.source.path)
    enum = DIALOG_STATE.search(content)
    if enum is None:
        raise errors.Refusal(
            refusals.RefusalReason.PATCH_SOURCE_UNEXPECTED, subject="missing dialog state enum"
        )
    target = bench.work / SOURCE_PATH
    patchbench.write(ports, target, content)
    patchbench.apply_patch(ports, bench)
    results = {
        "unpatched": _variant(ports, bench, "unpatched", content, template, enum.group()),
        "patched": _variant(
            ports, bench, "patched", patchbench.text(ports, target.path), template, enum.group()
        ),
    }
    judge(results)
    found: encoding.Document = {
        "status": PASS,
        "scope": SCOPE,
        "source": bench.source_label,
        "source_sha256": bench.source_digest.hex,
        "patch_sha256": bench.patch_digest.hex,
        **patchbench.environment(ports, bench),
        "cases": results,
        "gtk_integration": NOT_TESTED,
        "daemon_disappearance": HANDLER_ONLY,
        "async_scope": ASYNC_SCOPE,
        "fedora_rpm_build": NOT_TESTED,
        "physical_sensor": NOT_TESTED,
    }
    return patchbench.Checked(document=found, proof=patchbench.report(ports, bench, found))
