"""The two patch checks refuse root and an unreviewed source before anything is compiled,
and judge the harness the way the older runners did."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from apex.adapters.fakes import fake_process
from apex.adapters.real import real_files
from apex.config import defaults
from apex.kernel import errors, refusals, safepaths
from apex.ports import portset
from apex.verification import dialogcheck, elancheck, patchbench

REPOSITORY = safepaths.SourceRoot.adopt(Path(__file__).resolve().parents[3])
TOKEN = f"{1:032x}"
FLAGS = ("-I/usr/include/glib-2.0", "-lgio-2.0")
HANDLER = "\nstatic void\n{name} (int x)\n{{ if (x) {{ x++; }} }}\n"
ENUM = "typedef enum {\n  DIALOG_STATE_NONE = 0,\n} DialogState;\n"


@pytest.fixture
def root(tmp_path: Path) -> safepaths.RuntimeRoot:
    base = tmp_path / "runtime"
    base.mkdir(mode=0o700)
    return safepaths.RuntimeRoot.adopt(base)


@pytest.fixture(autouse=True)
def as_operator(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(patchbench.os, "geteuid", lambda: 1000)


def reviewed(tmp_path: Path, lock: str, key: str, content: str) -> Path:
    """A source whose digest the lock lists, made by writing the content and patching the lock."""
    source = tmp_path / "source.c"
    source.write_text(content)
    document = json.loads((REPOSITORY.path / lock).read_text())
    document[key][0]["sha256"] = __import__("hashlib").sha256(content.encode()).hexdigest()
    checkout = tmp_path / "checkout"
    (checkout / "config").mkdir(parents=True)
    (checkout / lock).write_text(json.dumps(document))
    for relative in (document["patch"], defaults.DIALOG_HARNESS_PATH, defaults.ELAN_HARNESS_PATH):
        target = checkout / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((REPOSITORY.path / relative).read_bytes())
    return source


def host(ports: portset.HostPorts, processes: fake_process.ScriptedProcess) -> portset.HostPorts:
    return dataclasses.replace(ports, files=real_files.LocalFiles(), processes=processes)


def test_root_is_refused_before_the_source_is_read(
    ports: portset.HostPorts,
    root: safepaths.RuntimeRoot,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(patchbench.os, "geteuid", lambda: 0)

    with pytest.raises(errors.Refusal) as raised:
        dialogcheck.check(
            host(ports, fake_process.ScriptedProcess()), root, REPOSITORY, tmp_path / "absent.c"
        )

    assert raised.value.reason is refusals.RefusalReason.HOST_RUNS_AS_ROOT


@pytest.mark.parametrize("check", [dialogcheck.check, elancheck.check])
def test_an_unreviewed_source_is_refused_before_any_program_runs(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot, tmp_path: Path, check: object
) -> None:
    source = tmp_path / "unreviewed.c"
    source.write_text("unreviewed code\n")
    processes = fake_process.ScriptedProcess()

    with pytest.raises(errors.Refusal) as raised:
        check(host(ports, processes), root, REPOSITORY, source)  # type: ignore[operator]

    assert raised.value.reason is refusals.RefusalReason.PATCH_SOURCE_NOT_REVIEWED
    assert processes.calls == []


def test_a_handler_is_extracted_whole_and_a_duplicate_is_refused() -> None:
    text = HANDLER.format(name="handle_enroll_signal")

    assert dialogcheck.function(text, "handle_enroll_signal").endswith("{ x++; } }")
    with pytest.raises(errors.Refusal) as raised:
        dialogcheck.function(text + text, "handle_enroll_signal")
    assert raised.value.reason is refusals.RefusalReason.PATCH_SOURCE_UNEXPECTED


def dialog_results(variant: str, case: str) -> dict[str, object]:
    patched = variant == "patched"
    counts = {
        "release_calls": 1,
        "stop_calls": 1,
        "cancel_calls": 0,
        "claim_calls": 0,
        "state_after_signal": 68,
        "state_after_callback": 4,
        "cancelled_callback": False,
    }
    if case in dialogcheck.CALLBACK_CASES:
        counts["stop_calls"] = 0
    if case in ("cancel", "cancel-twice"):
        counts["cancel_calls"] = 1
    if case in ("unclaimed", "daemon-gone"):
        counts["release_calls"] = 0
    if case == "daemon-gone":
        counts["claim_calls"] = 1
    if case == "close-pending":
        counts["cancelled_callback"] = True
    if not patched:
        counts.update(release_calls=0, cancel_calls=0, state_after_callback=196)
    return counts


def dialog_source() -> str:
    return ENUM + "".join(HANDLER.format(name=name) for name in dialogcheck.HANDLERS)


def dialog_processes(root: safepaths.RuntimeRoot, checkout: Path) -> fake_process.ScriptedProcess:
    work = root.path / defaults.DIALOG_TESTS_DIRECTORY / TOKEN / "work"
    patch = checkout / "rpms/patches/gnome-fingerprint-retain-claim.patch"
    replies = {
        ("pkg-config", "--cflags", "--libs", "gio-2.0"): fake_process.Reply(
            stdout=" ".join(FLAGS).encode()
        ),
        ("patch", "--batch", "--fuzz=0", "--forward", "-p1", "-i", str(patch)): (
            fake_process.Reply()
        ),
        ("cc", "--version"): fake_process.Reply(stdout=b"cc (GCC) 15.1\n"),
        ("pkg-config", "--modversion", "gio-2.0"): fake_process.Reply(stdout=b"2.88.3\n"),
    }
    for variant in ("unpatched", "patched"):
        replies[
            (
                "cc",
                "-std=c11",
                "-O0",
                "-Wall",
                "-Werror",
                "-Wno-unused-parameter",
                "-Wno-unused-function",
                f"{work}/{variant}.c",
                "-o",
                f"{work}/{variant}",
                *FLAGS,
            )
        ] = fake_process.Reply()
        for case in dialogcheck.CASES:
            replies[(f"{work}/{variant}", case)] = fake_process.Reply(
                stdout=json.dumps(dialog_results(variant, case)).encode()
            )
    return fake_process.ScriptedProcess(replies)


def test_the_dialog_check_patches_compiles_both_variants_and_judges_twelve_cases(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot, tmp_path: Path
) -> None:
    source = reviewed(tmp_path, defaults.DIALOG_LOCK_PATH, "reviewed_sources", dialog_source())
    checkout = safepaths.SourceRoot.adopt(tmp_path / "checkout")
    processes = dialog_processes(root, checkout.path)

    checked = dialogcheck.check(host(ports, processes), root, checkout, source)

    assert checked.document["status"] == "PASS"
    assert checked.document["source"] == "Fedora 50.4-1.fc44; no downstream patches"
    assert checked.document["gtk_integration"] == "NOT TESTED"
    assert checked.document["compiler"] == "cc (GCC) 15.1"
    assert checked.proof.path == (
        root.path / defaults.DIALOG_TESTS_DIRECTORY / TOKEN / "results.json"
    )
    kept = json.loads(checked.proof.path.read_text())
    assert kept["cases"]["patched"]["cancel"]["cancel_calls"] == 1
    programs = [tuple(call)[0] for call in processes.calls]
    assert programs[:2] == ["pkg-config", "patch"]
    assert programs.count("cc") == 3


def test_a_patched_handler_that_lost_its_cleanup_fails_the_check(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot, tmp_path: Path
) -> None:
    source = reviewed(tmp_path, defaults.DIALOG_LOCK_PATH, "reviewed_sources", dialog_source())
    checkout = safepaths.SourceRoot.adopt(tmp_path / "checkout")
    processes = dialog_processes(root, checkout.path)
    work = root.path / defaults.DIALOG_TESTS_DIRECTORY / TOKEN / "work"
    lost = {**dialog_results("patched", "retry"), "release_calls": 0}
    processes.expect(
        (f"{work}/patched", "retry"), fake_process.Reply(stdout=json.dumps(lost).encode())
    )

    with pytest.raises(errors.VerificationFailed) as failed:
        dialogcheck.check(host(ports, processes), root, checkout, source)

    assert failed.value.expected == "Patched handler lost Stop/Release cleanup"


def test_the_shipped_dialog_patch_only_preserves_the_cleanup_state() -> None:
    lock = json.loads((REPOSITORY.path / defaults.DIALOG_LOCK_PATH).read_text())
    patch = (REPOSITORY.path / lock["patch"]).read_text()
    lines = patch.splitlines()
    removed = [line for line in lines if line.startswith("-") and not line.startswith("---")]
    added = [line for line in lines if line.startswith("+") and not line.startswith("+++")]

    assert len(removed) == 2
    assert "DIALOG_STATE_DEVICE_CLAIMED" in removed[0]
    assert "DIALOG_STATE_DEVICE_ENROLLING" in removed[1]
    assert "if (self->dialog_state & DIALOG_STATE_DEVICE_ENROLL_STOPPING)" in patch
    assert all(
        "/*" in line or line.lstrip("+ ").startswith(("*", "if ", "return;")) or line == "+"
        for line in added
    )
    assert "experimental" in lock["status"]
    shipped = (REPOSITORY.path / "guest/build-rpms.sh").read_text()
    assert "gnome-fingerprint-retain-claim" not in shipped
    assert len(lock["reviewed_sources"]) == 2
    assert lock["reviewed_sources"][0]["sha256"] == lock["source_sha256"]
    assert lock["reviewed_sources"][1]["sha256"] != lock["source_sha256"]
    assert "not independently validated" in lock["source_trust"]


def test_the_dialog_harness_keeps_real_cancellation_and_no_bus() -> None:
    template = (REPOSITORY.path / defaults.DIALOG_HARNESS_PATH).read_text()

    assert {"enroll_stop", "enroll_stop_cb", "on_device_owner_changed"} <= set(dialogcheck.HANDLERS)
    assert {"cancel-twice", "close-pending", "daemon-gone", "stop-error"} <= set(dialogcheck.CASES)
    assert "#include <gio/gio.h>" in template
    assert "#define g_cancellable_cancel" not in template
    assert "g_bus_get" not in template


def elan_source() -> str:
    return (
        "/* driver */\n"
        f"{elancheck.HELPERS_START} anything */\n"
        "static void helper (void) { transfer->buffer[0]; }\n"
        f"{elancheck.HELPERS_END}\n"
        "apex_elan_trace_transfer (transfer, dev, error);\n"
        'apex_elan_emit (dev, ssm, "pre-scan-protocol", 1,\n'
    )


def elan_line(status: int) -> str:
    return (
        "apex-elan-v1 event=probe action=3 state=2 command=pre-scan expected=1 actual=1 "
        f"status={status} domain=0 code=0"
    )


def elan_processes(root: safepaths.RuntimeRoot, checkout: Path) -> fake_process.ScriptedProcess:
    work = root.path / defaults.ELAN_TESTS_DIRECTORY / TOKEN / "work"
    patch = checkout / "rpms/patches/libfprint-elan-status-diagnostics.patch"
    binary = f"{work}/harness"
    replies = {
        ("pkg-config", "--cflags", "--libs", "gio-2.0"): fake_process.Reply(
            stdout=" ".join(FLAGS).encode()
        ),
        ("git", "init", "-q"): fake_process.Reply(),
        ("git", "add", "--", elancheck.SOURCE_PATH): fake_process.Reply(),
        ("git", "apply", "--check", "--index", "-p1", str(patch)): fake_process.Reply(),
        ("patch", "--batch", "--fuzz=0", "--forward", "-p1", "-i", str(patch)): (
            fake_process.Reply()
        ),
        ("patch", "--batch", "--fuzz=0", "-R", "-p1", "-i", str(patch)): fake_process.Reply(),
        (
            "cc",
            "-std=c11",
            "-O0",
            "-Wall",
            "-Werror",
            "-Wno-unused-parameter",
            f"{work}/harness.c",
            "-o",
            binary,
            *FLAGS,
        ): fake_process.Reply(),
        ("cc", "--version"): fake_process.Reply(stdout=b"cc (GCC) 15.1\n"),
        ("pkg-config", "--modversion", "gio-2.0"): fake_process.Reply(stdout=b"2.88.3\n"),
    }
    for case in elancheck.SILENT:
        replies[(binary, case)] = fake_process.Reply()
    for case in elancheck.EXCLUDED:
        replies[(binary, case)] = fake_process.Reply(stdout=(elan_line(-1) + "\n").encode())
    for case in elancheck.STATUS:
        replies[(binary, case)] = fake_process.Reply(
            stdout=(elan_line(int(case[len("status-") :])) + "\n").encode()
        )
    replies[(binary, elancheck.BUDGET)] = fake_process.Reply(
        stdout=((elan_line(-1) + "\n") * elancheck.BUDGET_LINES).encode()
    )
    return fake_process.ScriptedProcess(replies)


def test_the_elan_check_applies_reverses_and_judges_twenty_cases(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot, tmp_path: Path
) -> None:
    source = reviewed(tmp_path, defaults.ELAN_LOCK_PATH, "sources", elan_source())
    checkout = safepaths.SourceRoot.adopt(tmp_path / "checkout")
    processes = elan_processes(root, checkout.path)

    checked = elancheck.check(host(ports, processes), root, checkout, source)

    assert checked.document["status"] == "PASS"
    assert checked.document["reverse_patch"] == "PASS"
    cases = checked.document["cases"]
    assert isinstance(cases, dict) and len(cases) == 20
    programs = [tuple(call)[:2] for call in processes.calls]
    assert programs[1:4] == [("git", "init"), ("git", "add"), ("git", "apply")]
    assert programs[-3] == ("patch", "--batch")


def test_a_case_that_leaks_a_payload_marker_fails(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot, tmp_path: Path
) -> None:
    source = reviewed(tmp_path, defaults.ELAN_LOCK_PATH, "sources", elan_source())
    checkout = safepaths.SourceRoot.adopt(tmp_path / "checkout")
    processes = elan_processes(root, checkout.path)
    binary = f"{root.path / defaults.ELAN_TESTS_DIRECTORY / TOKEN / 'work'}/harness"
    processes.expect(
        (binary, "status-85"),
        fake_process.Reply(stdout=(elan_line(85) + " PRIVATE_PAYLOAD_SENTINEL\n").encode()),
    )

    with pytest.raises(errors.VerificationFailed) as failed:
        elancheck.check(host(ports, processes), root, checkout, source)

    assert "status-85" in failed.value.expected


@pytest.mark.parametrize(
    "text",
    [
        "image-bytes",
        "apex-elan-v1 arbitrary=PRIVATE",
        "apex-elan-v1 event=probe action=3 state=2 command=pre-scan expected=1 actual=1 "
        "status=0 domain=0 code=0 payload=secret",
    ],
)
def test_the_output_contract_rejects_extra_payload(text: str) -> None:
    assert elancheck.LINE.fullmatch(text) is None


def test_the_shipped_elan_patch_is_opt_in_bounded_and_not_in_the_image() -> None:
    lock = json.loads((REPOSITORY.path / defaults.ELAN_LOCK_PATH).read_text())
    patch = (REPOSITORY.path / lock["patch"]).read_text()
    lines = patch.splitlines()
    added = "\n".join(
        line[1:] for line in lines if line.startswith("+") and not line.startswith("+++")
    )

    assert "disabled by default" in lock["status"]
    assert "self->apex_diag_events >= 16" in patch
    assert 'g_getenv ("APEX_ELAN_STATUS_DIAGNOSTICS"), "1"' in patch
    assert "== 0x04f3" in patch and "== 0x0c6e" in patch
    shipped = (REPOSITORY.path / "guest/build-rpms.sh").read_text()
    assert "libfprint-elan-status-diagnostics" not in shipped
    assert "error->message" not in added
    assert added.count("transfer->buffer[0]") == 1
    for condition in (
        "!error && self->cmd == &pre_scan_cmd",
        "transfer->endpoint == ELAN_EP_CMD_IN",
        "transfer->length == 1 && transfer->actual_length == 1",
        "transfer->buffer != NULL",
    ):
        assert condition in added
    assert "FP_DEBUG_TRANSFER" in added and "G_MESSAGES_DEBUG" in added
