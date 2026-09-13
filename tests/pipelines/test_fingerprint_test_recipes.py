"""The two fingerprint tests in the builder on fakes: inputs sent by digest, reports judged."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import posixpath
from pathlib import Path
from typing import Any

import fingerprintbuilds
import pytest
from answeringguest import AnsweringGuest
from mirroredfiles import MirroredFiles

from apex.adapters.real import real_digesting
from apex.composition import fingerprintpackages
from apex.composition import keys as composition_keys
from apex.config import defaults
from apex.kernel import refusals, safepaths
from apex.ports import guestshell, portset
from apex.verification import verifykeys
from apex.verification.recipes import fingerprint_gtk_recipe, fingerprint_rpms_test_recipe

REPOSITORY = safepaths.SourceRoot.adopt(Path(__file__).resolve().parents[2])
PRIVATE = defaults.RECORD_MODE


class DeliveringGuest(AnsweringGuest):
    """A guest whose retrieved output lands on the disk and in the file port."""

    def __init__(self, filesystem: MirroredFiles, outputs: dict[str, bytes]) -> None:
        super().__init__({})
        self.filesystem = filesystem
        self.outputs = outputs

    def receive(
        self, target: Any, *, remote: Any, into: Any, recursive: bool, deadline: Any
    ) -> None:
        super().receive(target, remote=remote, into=into, recursive=recursive, deadline=deadline)
        home = into.path / posixpath.basename(str(remote))
        for name, data in self.outputs.items():
            self.filesystem.write_atomic(safepaths.SafePath(home / name), data, mode=PRIVATE)


@pytest.fixture
def root(tmp_path: Path) -> safepaths.RuntimeRoot:
    base = tmp_path / "runtime"
    base.mkdir(mode=0o700)
    (base / "builder_ed25519").write_bytes(b"")
    return safepaths.RuntimeRoot.adopt(base)


def builder(root: safepaths.RuntimeRoot) -> guestshell.GuestTarget:
    return guestshell.GuestTarget(
        user=defaults.BUILDER_USER,
        port=defaults.BUILDER_SSH_PORT,
        key=safepaths.SafePath.regular_file(root.path / "builder_ed25519", within=root),
        known_hosts=root.child(defaults.KNOWN_HOSTS_NAME),
    )


def held(
    ports: portset.HostPorts, files: MirroredFiles, guest: DeliveringGuest
) -> portset.HostPorts:
    return dataclasses.replace(
        ports, files=files, guest=guest, digests=real_digesting.CachedDigests()
    )


def smoke_inputs() -> dict[str, str]:
    lock = fingerprintpackages.load_lock(REPOSITORY)
    names = fingerprintpackages.smoke_rpms(lock)
    return {name: hashlib.sha256(name.encode()).hexdigest() for name in names}


def smoke_report(**changes: Any) -> dict[str, Any]:
    return {
        "status": "PASS",
        "rpm_sha256": smoke_inputs(),
        "hardware": "NOT TESTED",
        "cases": {"fpi-ssm": {"status": "PASS"}, "fpi-device": {"status": "PASS"}},
        **changes,
    }


def test_the_smoke_test_sends_the_two_packages_by_digest_and_judges_the_report(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    files = MirroredFiles()
    fingerprintbuilds.rpm_build(files, root)
    guest = DeliveringGuest(files, {"results.json": json.dumps(smoke_report()).encode()})

    outcome = fingerprint_rpms_test_recipe.verify(
        held(ports, files, guest),
        builder=builder(root),
        parent=fingerprintbuilds.RPM_BUILD,
        root=root,
        repository=REPOSITORY,
    )

    assert outcome.succeeded, outcome.detail
    run = outcome.facts[composition_keys.RUN_ID]
    remote = f"/var/tmp/apex-fingerprint-rpm-tests-{run}"
    sent = [str(item.remote) for item in guest.sent]
    assert sum(name.startswith(f"{remote}/inputs/") for name in sent) == 2
    assert f"{remote}/inputs.json" in sent and f"{remote}/test.py" in sent
    assert any(
        r.script.rendered() == f"cd {remote} && sudo flock -n /run/apex-fingerprint-test.lock "
        "python3 test.py"
        for r in guest.runs
    )
    kept = outcome.facts[verifykeys.retained_report("fingerprint.rpm-smoke")]
    document = json.loads(files.read_bytes(kept, limit=1 << 20))
    assert document["verdict"] == "PASS" and document["inputs_sent"] == smoke_inputs()


def test_a_smoke_report_naming_other_packages_fails_and_is_kept(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    files = MirroredFiles()
    fingerprintbuilds.rpm_build(files, root)
    guest = DeliveringGuest(
        files, {"results.json": json.dumps(smoke_report(rpm_sha256={"x": "y"})).encode()}
    )

    outcome = fingerprint_rpms_test_recipe.verify(
        held(ports, files, guest),
        builder=builder(root),
        parent=fingerprintbuilds.RPM_BUILD,
        root=root,
        repository=REPOSITORY,
    )

    assert outcome.refusal is refusals.RefusalReason.STAGE_FAILED
    assert "other packages" in outcome.detail
    run = outcome.facts[composition_keys.RUN_ID]
    kept = json.loads((root.path / "exports" / str(run) / "fingerprint.rpm-smoke.json").read_text())
    assert kept["verdict"] == "FAIL"


def gtk_outputs(inputs: dict[str, str]) -> dict[str, bytes]:
    outputs: dict[str, bytes] = {}
    variants: dict[str, Any] = {}
    for variant in ("original", "patched"):
        cases = {}
        for case in fingerprintbuilds.CASES:
            log = f"{variant} {case}\n".encode()
            outputs[f"{variant}/{case}/dialog.log"] = log
            cases[case] = {"status": "PASS", "log_sha256": hashlib.sha256(log).hexdigest()}
        variants[variant] = cases
    report = {
        "status": "PASS",
        "inputs": inputs,
        "variants": variants,
        "patch_sha256": fingerprintbuilds.patch_digests()["gnome-control-center"],
    }
    outputs["results.json"] = json.dumps(report).encode()
    return outputs


def gtk_inputs(root: safepaths.RuntimeRoot) -> dict[str, str]:
    inputs = {
        name: hashlib.sha256((REPOSITORY.path / name).read_bytes()).hexdigest()
        for name in defaults.GTK_INPUT_FILES
    }
    lock = fingerprintpackages.load_lock(REPOSITORY)
    archive = lock.package("gnome-control-center").archive
    inputs[f"inputs/{archive}"] = hashlib.sha256(b"settings archive").hexdigest()
    return inputs


def test_the_dialog_test_sends_the_checkout_s_files_and_the_archive_and_checks_every_log(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    files = MirroredFiles()
    fingerprintbuilds.rpm_build(files, root)
    guest = DeliveringGuest(files, gtk_outputs(gtk_inputs(root)))

    outcome = fingerprint_gtk_recipe.verify(
        held(ports, files, guest),
        builder=builder(root),
        parent=fingerprintbuilds.RPM_BUILD,
        root=root,
        repository=REPOSITORY,
    )

    assert outcome.succeeded, outcome.detail
    run = outcome.facts[composition_keys.RUN_ID]
    remote = f"/var/tmp/apex-fingerprint-gtk-{run}"
    sent = [str(item.remote) for item in guest.sent]
    assert f"{remote}/guest/fingerprint-gtk.py" in sent and f"{remote}/request.json" in sent
    assert any(name.startswith(f"{remote}/inputs/gnome-control-center") for name in sent)
    assert any(
        r.script.rendered() == f"cd {remote} && flock -n test.lock python3 guest/fingerprint-gtk.py"
        for r in guest.runs
    )
    kept = json.loads(
        files.read_bytes(
            outcome.facts[verifykeys.retained_report("fingerprint.gtk")], limit=1 << 20
        )
    )
    assert kept["verdict"] == "PASS" and len(kept["inputs_sent"]) == 6


def test_a_dialog_log_that_differs_from_its_digest_fails_the_run(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    files = MirroredFiles()
    fingerprintbuilds.rpm_build(files, root)
    outputs = gtk_outputs(gtk_inputs(root))
    outputs["patched/cancel-twice/dialog.log"] = b"rewritten"
    guest = DeliveringGuest(files, outputs)

    outcome = fingerprint_gtk_recipe.verify(
        held(ports, files, guest),
        builder=builder(root),
        parent=fingerprintbuilds.RPM_BUILD,
        root=root,
        repository=REPOSITORY,
    )

    assert outcome.refusal is refusals.RefusalReason.STAGE_FAILED
    assert "cancel-twice" in outcome.detail
