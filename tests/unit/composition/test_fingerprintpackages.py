"""The fingerprint package reports are bound to the checkout's lock, patches and packages."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import fingerprintbuilds
import pytest
from mirroredfiles import MirroredFiles

from apex.composition import artifactchecks, exports, fingerprintpackages
from apex.kernel import errors, identifiers, refusals, safepaths

REPOSITORY = safepaths.SourceRoot.adopt(Path(__file__).resolve().parents[3])


@pytest.fixture
def root(tmp_path: Path) -> safepaths.RuntimeRoot:
    base = tmp_path / "runtime"
    base.mkdir(mode=0o700)
    return safepaths.RuntimeRoot.adopt(base)


def lock() -> fingerprintpackages.PackageLock:
    return fingerprintpackages.load_lock(REPOSITORY)


def patches() -> dict[str, identifiers.Digest]:
    return {
        name: identifiers.Digest(value) for name, value in fingerprintbuilds.patch_digests().items()
    }


def test_the_lock_names_the_library_and_the_settings_and_the_names_carry_the_release() -> None:
    held = lock()

    assert [item.name for item in held.packages] == ["libfprint", "gnome-control-center"]
    assert fingerprintpackages.release().endswith(".apex1")
    names = fingerprintpackages.image_rpms(held)
    assert len(names) == 3 and names[2].endswith(".noarch.rpm")
    assert all(fingerprintpackages.release() in name for name in names)
    assert fingerprintpackages.smoke_rpms(held)[1].startswith("libfprint-tests-")


def test_a_transferred_report_and_its_artifacts_are_verified(
    ports: Any, root: safepaths.RuntimeRoot
) -> None:
    files = MirroredFiles()
    report = fingerprintbuilds.rpm_build(files, root)

    parsed = fingerprintpackages.parse_rpm_report(report, lock(), patches())
    artifactchecks.require_artifacts(
        ports, root, exports.inside(root, fingerprintbuilds.RPM_BUILD, "output"), parsed.artifacts
    )

    assert set(parsed.patches) == {"libfprint", "gnome-control-center"}


@pytest.mark.parametrize(
    "fault", ["hardware-pass", "missing-package", "patch", "missing-rpm", "escape", "other-lock"]
)
def test_an_incomplete_or_unbound_report_is_refused(
    root: safepaths.RuntimeRoot, fault: str
) -> None:
    report = copy.deepcopy(fingerprintbuilds.rpm_build(MirroredFiles(), root))
    if fault == "hardware-pass":
        report["hardware"] = "PASS"
    elif fault == "missing-package":
        del report["packages"]["libfprint"]
    elif fault == "patch":
        report["packages"]["libfprint"]["patch_sha256"] = "d" * 64
    elif fault == "missing-rpm":
        del report["artifacts"][next(k for k in report["artifacts"] if "/mock/" in k)]
    elif fault == "escape":
        report["artifacts"]["../outside"] = "e" * 64
    else:
        report["source_lock_sha256"] = "f" * 64

    with pytest.raises(errors.Refusal) as raised:
        fingerprintpackages.parse_rpm_report(report, lock(), patches())

    assert raised.value.reason is refusals.RefusalReason.FINGERPRINT_REPORT_UNBOUND


def test_a_tampered_artifact_is_a_checksum_mismatch(
    ports: Any, root: safepaths.RuntimeRoot
) -> None:
    files = MirroredFiles()
    report = fingerprintbuilds.rpm_build(files, root)
    home = exports.inside(root, fingerprintbuilds.RPM_BUILD, "output")
    tampered = next(k for k in report["artifacts"] if "/mock/" in k)
    (home.path / tampered).write_bytes(b"changed")
    parsed = fingerprintpackages.parse_rpm_report(report, lock(), patches())

    with pytest.raises(errors.Refusal) as raised:
        artifactchecks.require_artifacts(ports, root, home, parsed.artifacts)

    assert raised.value.reason is refusals.RefusalReason.ARTIFACT_CHECKSUM_MISMATCH


def test_a_dialog_report_names_its_logs_and_a_lost_log_is_refused(
    ports: Any, root: safepaths.RuntimeRoot
) -> None:
    files = MirroredFiles()
    report = fingerprintbuilds.gtk_test(files, root)
    home = exports.inside(root, fingerprintbuilds.GTK_TEST, "output")

    parsed = fingerprintpackages.parse_gtk_report(report)
    fingerprintpackages.require_gtk_logs(ports, root, home, parsed)
    assert len(parsed.logs) == 10
    assert parsed.patch == fingerprintbuilds.patch_digests()["gnome-control-center"]
    (home.path / "patched" / "cancel-twice" / "dialog.log").write_bytes(b"rewritten")
    ports.digests.forget()
    with pytest.raises(errors.Refusal):
        fingerprintpackages.require_gtk_logs(ports, root, home, parsed)


def test_the_smoke_judgement_needs_both_programs_the_sent_packages_and_no_hardware_claim() -> None:
    inputs = {"a.rpm": "1" * 64, "b.rpm": "2" * 64}
    passed = {
        "status": "PASS",
        "rpm_sha256": inputs,
        "hardware": "NOT TESTED",
        "cases": {"fpi-ssm": {"status": "PASS"}, "fpi-device": {"status": "PASS"}},
    }

    assert fingerprintpackages.judge_smoke(passed, inputs) is None
    assert fingerprintpackages.judge_smoke({**passed, "hardware": "PASS"}, inputs)
    assert fingerprintpackages.judge_smoke({**passed, "rpm_sha256": {}}, inputs)
    one_case = {**passed, "cases": {"fpi-ssm": {"status": "PASS"}}}
    assert fingerprintpackages.judge_smoke(one_case, inputs)
    assert fingerprintpackages.judge_gtk(
        fingerprintpackages.GtkReport(document={}, inputs=inputs, patch="", logs={}), {"x": "y"}
    )
