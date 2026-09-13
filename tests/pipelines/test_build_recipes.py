"""The three build recipes, run end to end on fakes.

A small checkout carries the reviewed lock, so the source stages are real; every effect on
the guest lands in the scripted guest's journal, and every refusal happens before it.
"""

from __future__ import annotations

import dataclasses
import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from apex.adapters.fakes import (
    fake_archives,
    fake_clock,
    fake_digesting,
    fake_downloading,
    fake_files,
    fake_guestshell,
    fake_hypervisor,
    fake_ids,
    fake_locking,
    fake_process,
    fake_qmp,
    fake_signing,
)
from apex.composition import exports, keys
from apex.composition.recipes import disk_artifact_recipe, image_recipe, live_artifact_recipe
from apex.config import defaults
from apex.kernel import hashing, identifiers, quantities, refusals, safepaths
from apex.model import builds
from apex.pipeline import stages
from apex.pipeline.facts import FactMap
from apex.ports import guestshell, portset

REPOSITORY = Path(__file__).resolve().parents[2]
PARENT = identifiers.BuildId("b" * 32)
IMAGE_ID = "c" * 64


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


@pytest.fixture
def guest() -> fake_guestshell.ScriptedGuest:
    return fake_guestshell.ScriptedGuest()


@pytest.fixture
def ports(guest: fake_guestshell.ScriptedGuest) -> portset.HostPorts:
    return portset.HostPorts(
        processes=fake_process.ScriptedProcess(),
        files=fake_files.MemoryFiles(),
        clock=fake_clock.ManualClock(),
        identities=fake_ids.SequenceIdentities(),
        locks=fake_locking.MemoryLocks(),
        digests=fake_digesting.CountingDigests(),
        archives=fake_archives.MemoryArchives(),
        signing=fake_signing.FakeSigner(),
        downloads=fake_downloading.PinningFetcher(),
        hypervisor=fake_hypervisor.FakeQemu(),
        monitor=fake_qmp.ScriptedQmp(),
        guest=guest,
    )


def builder(root: safepaths.RuntimeRoot) -> guestshell.GuestTarget:
    return guestshell.GuestTarget(
        user=defaults.BUILDER_USER,
        port=defaults.BUILDER_SSH_PORT,
        key=safepaths.SafePath.regular_file(root.path / "builder_ed25519", within=root),
        known_hosts=root.child(defaults.KNOWN_HOSTS_NAME),
    )


def memory(ports: portset.HostPorts) -> fake_files.MemoryFiles:
    assert isinstance(ports.files, fake_files.MemoryFiles)
    return ports.files


def parent_documents(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot, *, image_id: str = IMAGE_ID
) -> None:
    manifest = json.dumps({"config": {"digest": f"sha256:{IMAGE_ID}"}}).encode()
    image = json.dumps({
        "profile": "fedora",
        "digest": str(hashing.digest_bytes(manifest)),
        "image_id": f"sha256:{image_id}",
    }).encode()
    record = json.dumps({
        "status": "PASS", "kind": "image", "profile": "fedora", "source_sha256": "a" * 64,
        "remote": f"/var/tmp/apex-{PARENT}", "parent_build": None, "test_access": False,
    }).encode()
    mode = quantities.FileMode(0o600)
    ports.files.write_atomic(exports.inside(root, PARENT, "result.json"), record, mode=mode)
    ports.files.write_atomic(exports.inside(root, PARENT, "output/image.json"), image, mode=mode)
    ports.files.write_atomic(
        exports.inside(root, PARENT, "output/manifest.json"), manifest, mode=mode
    )


def scripts(guest: fake_guestshell.ScriptedGuest) -> list[str]:
    return [run.script.rendered() for run in guest.runs]


def test_the_plan_puts_every_local_decision_before_the_first_remote_effect() -> None:
    order = [str(item) for item in image_recipe.PLAN.order]

    assert order.index("build.freeze") < order.index("builder.check")
    assert order.index("builder.check") < order.index("sources.acquire")
    assert order[-5:] == [
        "guest.transfer", "access.grant", "build.run", "build.retrieve", "build.record",
    ]


def test_an_image_build_runs_the_older_tree_s_three_guest_scripts(
    ports: portset.HostPorts, guest: fake_guestshell.ScriptedGuest,
    repository: safepaths.SourceRoot, root: safepaths.RuntimeRoot,
) -> None:
    outcome = image_recipe.build(
        ports, repository=repository, runtime_root=root, builder=builder(root),
        profile=builds.Profile.FEDORA,
    )

    assert outcome.succeeded, outcome.detail
    run = outcome.facts[keys.RUN_ID]
    remote = f"/var/tmp/apex-{run}"
    assert scripts(guest) == [
        "test -f /etc/apex-builder && systemd-detect-virt --quiet --vm",
        f"mkdir -m 700 {remote}",
        f"cd {remote} && tar -xf source.tar && sudo flock -n /run/apex-build.lock bash -c "
        "'bash guest/bootstrap.sh && bash guest/build.sh fedora image'",
        f"sudo chown -R builder:builder {remote}/output 2>/dev/null || true",
    ]
    assert [str(item.remote) for item in guest.sent] == [f"{remote}/source.tar"]
    assert [str(item.remote) for item in guest.received] == [f"{remote}/output"]
    record = json.loads(
        memory(ports).read_bytes(exports.inside(root, run, "result.json"), limit=4096)
    )
    assert record["status"] == "PASS"
    assert record["kind"] == "image"
    assert outcome.facts[keys.BUILD_RECORD].status is builds.BuildStatus.PASS


def test_an_unreviewed_profile_is_refused_before_any_effect(
    ports: portset.HostPorts, guest: fake_guestshell.ScriptedGuest,
    repository: safepaths.SourceRoot, root: safepaths.RuntimeRoot,
) -> None:
    outcome = image_recipe.build(
        ports, repository=repository, runtime_root=root, builder=builder(root),
        profile=builds.Profile.CACHYOS,
    )

    assert not outcome.succeeded
    assert outcome.refusal is refusals.RefusalReason.BUILD_PROFILE_NOT_REVIEWED
    assert guest.runs == []
    assert memory(ports).writes == []


def test_a_disk_artifact_imports_the_frozen_payload_and_signs_the_output(
    ports: portset.HostPorts, guest: fake_guestshell.ScriptedGuest,
    repository: safepaths.SourceRoot, root: safepaths.RuntimeRoot,
) -> None:
    parent_documents(ports, root)

    outcome = disk_artifact_recipe.derive(
        ports, repository=repository, runtime_root=root, builder=builder(root),
        kind=builds.ArtifactKind.INSTALLER, parent=PARENT,
    )

    assert outcome.succeeded, outcome.detail
    run = outcome.facts[keys.RUN_ID]
    remote = f"/var/tmp/apex-{run}"
    payload = f"/var/tmp/apex-{PARENT}/output/apex-fedora.oci.tar"
    assert scripts(guest)[2] == (
        f"cd {remote} && tar -xf source.tar && sudo flock -n /run/apex-build.lock bash -c "
        f"'bash guest/bootstrap.sh && bash guest/import-payload.sh {payload} target-image.json"
        f" && bash guest/disk-artifact.sh installer sha256:{IMAGE_ID} {payload}"
        " && python3 guest/sign-artifacts.py output target-image.json'"
    )
    assert [str(item.remote) for item in guest.sent] == [
        f"{remote}/source.tar", f"{remote}/target-image.json",
    ]
    assert outcome.facts[keys.BUILD_RECORD].parent == PARENT


def test_a_live_artifact_uses_the_live_script_without_the_archive_argument(
    ports: portset.HostPorts, guest: fake_guestshell.ScriptedGuest,
    repository: safepaths.SourceRoot, root: safepaths.RuntimeRoot,
) -> None:
    parent_documents(ports, root)

    outcome = live_artifact_recipe.derive(
        ports, repository=repository, runtime_root=root, builder=builder(root), parent=PARENT,
    )

    assert outcome.succeeded, outcome.detail
    assert f"bash guest/live-artifact.sh live sha256:{IMAGE_ID} &&" in scripts(guest)[2]


def test_a_derived_artifact_without_a_parent_is_refused_in_preflight(
    ports: portset.HostPorts, guest: fake_guestshell.ScriptedGuest,
    repository: safepaths.SourceRoot, root: safepaths.RuntimeRoot,
) -> None:
    outcome = disk_artifact_recipe.PLAN
    result = image_recipe.PLAN  # both plans share the stages; the seed decides
    assert outcome.order == result.order

    from apex.composition import buildplan  # noqa: PLC0415

    ran = buildplan.run(
        disk_artifact_recipe.PLAN, ports, repository=repository, runtime_root=root,
        builder=builder(root), profile=builds.Profile.FEDORA, kind=builds.ArtifactKind.QCOW2,
        parent=None,
    )

    assert ran.refusal is refusals.RefusalReason.BUILD_PARENT_REQUIRED
    assert guest.runs == []


def test_a_parent_whose_documents_disagree_is_refused_before_the_guest_is_touched(
    ports: portset.HostPorts, guest: fake_guestshell.ScriptedGuest,
    repository: safepaths.SourceRoot, root: safepaths.RuntimeRoot,
) -> None:
    parent_documents(ports, root, image_id="d" * 64)

    outcome = disk_artifact_recipe.derive(
        ports, repository=repository, runtime_root=root, builder=builder(root),
        kind=builds.ArtifactKind.QCOW2, parent=PARENT,
    )

    assert outcome.refusal is refusals.RefusalReason.FROZEN_IMAGE_MISMATCH
    assert guest.runs == []


def test_a_failed_guest_build_is_recorded_and_its_output_still_retrieved(
    ports: portset.HostPorts, guest: fake_guestshell.ScriptedGuest,
    repository: safepaths.SourceRoot, root: safepaths.RuntimeRoot,
) -> None:
    run = identifiers.RunId(f"{1:032x}")
    remote = f"/var/tmp/apex-{run}"
    guest.expect(
        f"cd {remote} && tar -xf source.tar && sudo flock -n /run/apex-build.lock bash -c "
        "'bash guest/bootstrap.sh && bash guest/build.sh fedora image'",
        fake_guestshell.GuestReply(exit_code=3),
    )

    outcome = image_recipe.build(
        ports, repository=repository, runtime_root=root, builder=builder(root),
        profile=builds.Profile.FEDORA,
    )

    assert not outcome.succeeded
    assert "exited with 3" in outcome.detail
    assert [str(item.remote) for item in guest.received] == [f"{remote}/output"]
    record = json.loads(
        memory(ports).read_bytes(exports.inside(root, run, "result.json"), limit=4096)
    )
    assert record["status"] == "FAIL"


def test_every_stage_only_computes_while_the_plan_is_checked(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot,
) -> None:
    given = FactMap()
    for key, value in (
        (keys.KIND, builds.ArtifactKind.IMAGE),
        (keys.PARENT, None),
        (keys.REQUESTED_PROFILE, builds.Profile.FEDORA),
        (keys.TEST_ACCESS, False),
    ):
        given = given.with_fact(key, value, produced_by=identifiers.StageId("seed"))
    context = stages.RunContext(facts=given, ports=ports.for_planning())

    for stage in image_recipe.PLAN.stages:
        assert stage.preflight(context) == stages.Ready()


class AccountGuest(fake_process.ScriptedProcess):
    """The two host tools a disposable account needs, answered against the fake files."""

    def __init__(self, files: fake_files.MemoryFiles) -> None:
        super().__init__()
        self.files = files

    def run(self, argv: Any, **keywords: Any) -> Any:
        vector = tuple(str(item) for item in argv)
        if vector[:1] == ("ssh-keygen",):
            key = Path(vector[-1])
            for suffix, body in (("", b"private"), (".pub", b"ssh-ed25519 AAAA test\n")):
                self.files.write_atomic(
                    safepaths.SafePath(key.with_name(key.name + suffix)), body,
                    mode=quantities.FileMode(0o600),
                )
            self.expect(vector, fake_process.Reply())
        elif vector[:2] == ("openssl", "passwd"):
            self.expect(vector, fake_process.Reply(stdout=b"$6$hashed\n"))
        return super().run(argv, **keywords)


def test_the_plan_grants_the_account_after_the_transfer_and_before_the_build() -> None:
    order = [str(item) for item in disk_artifact_recipe.PLAN.order]

    assert order.index("guest.transfer") < order.index("access.grant") < order.index("build.run")


def test_a_qcow2_with_test_access_carries_the_blueprint_and_says_so_in_its_record(
    ports: portset.HostPorts, guest: fake_guestshell.ScriptedGuest,
    repository: safepaths.SourceRoot, root: safepaths.RuntimeRoot,
) -> None:
    parent_documents(ports, root)
    held = dataclasses.replace(ports, processes=AccountGuest(memory(ports)))

    outcome = disk_artifact_recipe.derive(
        held, repository=repository, runtime_root=root, builder=builder(root),
        kind=builds.ArtifactKind.QCOW2, parent=PARENT, test_access=True,
    )

    assert outcome.succeeded, outcome.detail
    run = outcome.facts[keys.RUN_ID]
    remote = f"/var/tmp/apex-{run}"
    assert [str(item.remote) for item in guest.sent] == [
        f"{remote}/source.tar", f"{remote}/target-image.json", f"{remote}/test-blueprint.toml",
    ]
    granted = outcome.facts[keys.ACCESS]
    assert granted is not None
    access = root.path / "exports" / str(run) / "test-access"
    assert granted.credentials.path == access / "credentials.json"
    record = json.loads(
        memory(ports).read_bytes(exports.inside(root, run, "result.json"), limit=4096)
    )
    assert record["test_access"] is True
    assert scripts(guest)[2].startswith(f"cd {remote} && tar -xf source.tar")


def test_test_access_on_anything_but_a_qcow2_is_refused_before_the_guest_is_touched(
    ports: portset.HostPorts, guest: fake_guestshell.ScriptedGuest,
    repository: safepaths.SourceRoot, root: safepaths.RuntimeRoot,
) -> None:
    parent_documents(ports, root)

    outcome = disk_artifact_recipe.derive(
        ports, repository=repository, runtime_root=root, builder=builder(root),
        kind=builds.ArtifactKind.INSTALLER, parent=PARENT, test_access=True,
    )

    assert outcome.refusal is refusals.RefusalReason.TEST_ACCESS_NOT_QCOW2
    assert guest.runs == [] and guest.sent == []


def test_without_test_access_no_account_is_made_and_the_record_says_so(
    ports: portset.HostPorts, guest: fake_guestshell.ScriptedGuest,
    repository: safepaths.SourceRoot, root: safepaths.RuntimeRoot,
) -> None:
    parent_documents(ports, root)

    outcome = disk_artifact_recipe.derive(
        ports, repository=repository, runtime_root=root, builder=builder(root),
        kind=builds.ArtifactKind.QCOW2, parent=PARENT,
    )

    assert outcome.succeeded, outcome.detail
    assert outcome.facts[keys.ACCESS] is None
    assert outcome.facts[keys.BUILD_RECORD].test_access is False
    assert not any(str(item.remote).endswith("test-blueprint.toml") for item in guest.sent)
