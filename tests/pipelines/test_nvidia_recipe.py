"""The NVIDIA build on fakes: the lock read first, the guest asked once, the report bound."""

from __future__ import annotations

import dataclasses
import json
import posixpath
import shutil
from pathlib import Path
from typing import Any

import nvidialockfixture as fixture
import parentbuild
import pytest

from apex.adapters.fakes import fake_downloading, fake_files, fake_guestshell
from apex.composition import exports, keys
from apex.composition.recipes import nvidia_recipe
from apex.config import defaults
from apex.kernel import refusals, safepaths
from apex.ports import guestshell, portset

REPOSITORY = Path(__file__).resolve().parents[2]
PARENT = parentbuild.PARENT
IMAGE_ID = parentbuild.IMAGE_ID


class DeliveringGuest(fake_guestshell.ScriptedGuest):
    """A guest whose retrieved output lands on the disk and in the file port, as a copy would."""

    def __init__(self, filesystem: fake_files.MemoryFiles, report: dict[str, object]) -> None:
        super().__init__()
        self.filesystem = filesystem
        self.report = report

    def receive(
        self,
        target: guestshell.GuestTarget,
        *,
        remote: safepaths.RemotePath,
        into: safepaths.SafePath,
        recursive: bool,
        deadline: Any,
    ) -> None:
        super().receive(target, remote=remote, into=into, recursive=recursive, deadline=deadline)
        home = into.path / posixpath.basename(str(remote)) / defaults.NVIDIA_OUTPUT_DIRECTORY
        for name, data in fixture.artifacts().items():
            (home / name).parent.mkdir(parents=True, exist_ok=True)
            (home / name).write_bytes(data)
        self.filesystem.write_atomic(
            safepaths.SafePath(home / defaults.NVIDIA_REPORT_NAME),
            json.dumps(self.report).encode(),
            mode=fixture.PRIVATE,
        )


@pytest.fixture
def repository(tmp_path: Path) -> safepaths.SourceRoot:
    checkout = tmp_path / "checkout"
    (checkout / "config").mkdir(parents=True)
    shutil.copy(REPOSITORY / "config" / "sources.lock.json", checkout / "config")
    (checkout / "Containerfile").write_text("FROM scratch\n")
    return safepaths.SourceRoot.adopt(checkout)


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


def prepared(
    ports: portset.HostPorts,
    repository: safepaths.SourceRoot,
    root: safepaths.RuntimeRoot,
    *,
    report: dict[str, object] | None = None,
    compiler: str = fixture.COMPILER,
) -> tuple[portset.HostPorts, DeliveringGuest]:
    filesystem = fake_files.MemoryFiles()
    fixture.write_lock(repository.path, filesystem)
    parentbuild.documents(filesystem, root, PARENT)
    filesystem.write_atomic(
        exports.inside(root, PARENT, f"output/{defaults.KERNEL_CONFIG_NAME}"),
        fixture.kernel_config(compiler),
        mode=fixture.PRIVATE,
    )
    guest = DeliveringGuest(filesystem, fixture.report(IMAGE_ID) if report is None else report)
    return dataclasses.replace(
        ports, files=filesystem, guest=guest, downloads=fake_downloading.PinningFetcher()
    ), guest


def build(
    ports: portset.HostPorts, repository: safepaths.SourceRoot, root: safepaths.RuntimeRoot
) -> Any:
    return nvidia_recipe.build(
        ports, repository=repository, runtime_root=root, builder=builder(root), parent=PARENT
    )


def test_the_plan_reads_the_lock_before_the_transfer_and_records_last() -> None:
    order = [str(item) for item in nvidia_recipe.PLAN.order]

    assert order.index("nvidia.lock") < order.index("guest.prepare")
    assert order[-3:] == ["build.run", "build.retrieve", "nvidia.record"]
    assert "build.record" not in order


def test_the_packages_are_built_over_the_imported_payload_and_the_report_is_bound(
    ports: portset.HostPorts, repository: safepaths.SourceRoot, root: safepaths.RuntimeRoot
) -> None:
    held, guest = prepared(ports, repository, root)

    outcome = build(held, repository, root)

    assert outcome.succeeded, outcome.detail
    run = outcome.facts[keys.RUN_ID]
    remote = f"/var/tmp/apex-{run}"
    payload = f"/var/tmp/apex-{PARENT}/output/apex-fedora.oci.tar"
    assert [item.script.rendered() for item in guest.runs][2] == (
        f"cd {remote} && tar -xf source.tar && sudo flock -n /run/apex-build.lock bash -c "
        f"'bash guest/bootstrap.sh && bash guest/import-payload.sh {payload} target-image.json"
        f" && python3 guest/nvidia-build.py sha256:{IMAGE_ID}'"
    )
    record = outcome.facts[keys.BUILD_RECORD]
    assert str(record.kind) == "nvidia" and str(record.status) == "PASS"
    assert record.parent == PARENT and record.test_access is False
    assert outcome.facts[keys.NVIDIA_REPORT]["stage"] == "rpm-build"
    verification = json.loads(
        held.files.read_bytes(
            exports.inside(root, run, defaults.NVIDIA_VERIFICATION_NAME), limit=4096
        )
    )
    assert verification == {
        "status": "PASS",
        "reason": "",
        "parent_build": str(PARENT),
        "ready_to_install": False,
    }


def test_a_parent_compiled_by_another_compiler_is_refused_before_anything_is_sent(
    ports: portset.HostPorts, repository: safepaths.SourceRoot, root: safepaths.RuntimeRoot
) -> None:
    held, guest = prepared(ports, repository, root, compiler="gcc (GCC) 15.0")

    outcome = build(held, repository, root)

    assert outcome.refusal is refusals.RefusalReason.NVIDIA_COMPILER_MISMATCH
    assert guest.sent == [] and guest.received == []


def test_a_report_the_host_cannot_bind_leaves_a_failed_record_and_says_why(
    ports: portset.HostPorts, repository: safepaths.SourceRoot, root: safepaths.RuntimeRoot
) -> None:
    held, _ = prepared(ports, repository, root, report=fixture.report(IMAGE_ID, hardware="PASS"))

    outcome = build(held, repository, root)

    assert not outcome.succeeded
    assert "was not accepted" in outcome.detail and "claims a test" in outcome.detail
    run = outcome.facts[keys.RUN_ID]
    record = json.loads(held.files.read_bytes(exports.inside(root, run, "result.json"), limit=4096))
    assert record["status"] == "FAIL" and record["kind"] == "nvidia"
    verification = json.loads(
        held.files.read_bytes(
            exports.inside(root, run, defaults.NVIDIA_VERIFICATION_NAME), limit=4096
        )
    )
    assert verification["status"] == "FAIL" and "claims a test" in verification["reason"]


def test_a_failed_guest_build_is_recorded_with_its_log_and_nothing_is_bound(
    ports: portset.HostPorts, repository: safepaths.SourceRoot, root: safepaths.RuntimeRoot
) -> None:
    held, guest = prepared(ports, repository, root)
    run_id = f"{1:032x}"
    remote = f"/var/tmp/apex-{run_id}"
    payload = f"/var/tmp/apex-{PARENT}/output/apex-fedora.oci.tar"
    guest.expect(
        f"cd {remote} && tar -xf source.tar && sudo flock -n /run/apex-build.lock bash -c "
        f"'bash guest/bootstrap.sh && bash guest/import-payload.sh {payload} target-image.json"
        f" && python3 guest/nvidia-build.py sha256:{IMAGE_ID}'",
        fake_guestshell.GuestReply(exit_code=4),
    )

    outcome = build(held, repository, root)

    assert not outcome.succeeded and "exited with 4" in outcome.detail
    run = outcome.facts[keys.RUN_ID]
    record = json.loads(held.files.read_bytes(exports.inside(root, run, "result.json"), limit=4096))
    assert record["status"] == "FAIL"
    verification = json.loads(
        held.files.read_bytes(
            exports.inside(root, run, defaults.NVIDIA_VERIFICATION_NAME), limit=4096
        )
    )
    assert verification["reason"] == "the guest build failed"
