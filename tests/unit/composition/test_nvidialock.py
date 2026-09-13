"""The reviewed NVIDIA lock, the compiler it binds, and the report it must bind."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import nvidialockfixture as fixture
import pytest

from apex.adapters.fakes import fake_files
from apex.composition import exports, nvidialock
from apex.config import defaults
from apex.kernel import errors, identifiers, refusals, safepaths
from apex.model import oci
from apex.ports import portset

PARENT = identifiers.BuildId("d" * 32)
IMAGE_ID = "b" * 64
FROZEN = oci.FrozenImage(
    profile="fedora", digest=identifiers.Digest("c" * 64),
    image_id=identifiers.ImageId(IMAGE_ID),
)


@pytest.fixture
def root(tmp_path: Path) -> safepaths.RuntimeRoot:
    base = tmp_path / "runtime"
    base.mkdir(mode=0o700)
    return safepaths.RuntimeRoot.adopt(base)


@pytest.fixture
def repository(tmp_path: Path) -> safepaths.SourceRoot:
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    return safepaths.SourceRoot.adopt(checkout)


def held(ports: portset.HostPorts) -> portset.HostPorts:
    return dataclasses.replace(ports, files=fake_files.MemoryFiles())


def test_the_lock_is_read_with_its_digest_and_names_every_expected_package(
    ports: portset.HostPorts, repository: safepaths.SourceRoot
) -> None:
    bundle = held(ports)
    expected = fixture.write_lock(repository.path, bundle.files)

    lock = nvidialock.load(bundle, repository)

    assert lock.version == fixture.VERSION and lock.kernel_release == fixture.KERNEL
    assert lock.compiler_text == fixture.COMPILER and lock.digest.hex == expected
    assert lock.kmod_path == fixture.KMOD
    assert lock.expected_rpms == frozenset({
        *(f"packages/{name}-{fixture.VERSION}-1.fc44.x86_64.rpm" for name in fixture.VENDOR),
        fixture.KMOD,
    })


def test_a_lock_that_is_missing_or_malformed_is_refused_by_name(
    ports: portset.HostPorts, repository: safepaths.SourceRoot
) -> None:
    bundle = held(ports)
    with pytest.raises(errors.Refusal) as absent:
        nvidialock.load(bundle, repository)
    target = repository.path / defaults.NVIDIA_LOCK_PATH
    target.parent.mkdir(parents=True)
    target.write_bytes(b"{}")
    bundle.files.write_atomic(safepaths.SafePath(target), b"{}", mode=fixture.PRIVATE)
    with pytest.raises(errors.Refusal) as malformed:
        nvidialock.load(bundle, repository)

    assert absent.value.reason is refusals.RefusalReason.NVIDIA_LOCK_MALFORMED
    assert malformed.value.reason is refusals.RefusalReason.NVIDIA_LOCK_MALFORMED


def test_the_parent_s_compiler_must_be_the_lock_s(
    ports: portset.HostPorts, repository: safepaths.SourceRoot, root: safepaths.RuntimeRoot
) -> None:
    bundle = held(ports)
    fixture.write_lock(repository.path, bundle.files)
    lock = nvidialock.load(bundle, repository)
    config = exports.inside(root, PARENT, f"output/{defaults.KERNEL_CONFIG_NAME}")

    with pytest.raises(errors.Refusal) as absent:
        nvidialock.require_compiler(bundle, root, PARENT, lock)
    bundle.files.write_atomic(config, fixture.kernel_config("gcc (GCC) 15.0"), mode=fixture.PRIVATE)
    with pytest.raises(errors.Refusal) as other:
        nvidialock.require_compiler(bundle, root, PARENT, lock)
    bundle.files.write_atomic(config, fixture.kernel_config(), mode=fixture.PRIVATE)
    nvidialock.require_compiler(bundle, root, PARENT, lock)

    assert absent.value.reason is refusals.RefusalReason.BUILD_PARENT_NOT_COMPLETE
    assert other.value.reason is refusals.RefusalReason.NVIDIA_COMPILER_MISMATCH


def output(
    bundle: portset.HostPorts, root: safepaths.RuntimeRoot, report: dict[str, object],
    *, artifacts: dict[str, bytes] | None = None,
) -> safepaths.SafePath:
    """The guest's output on the disk, for the digests, and its report in the file port."""
    home = root.child(f"exports/{'e' * 32}/output/{defaults.NVIDIA_OUTPUT_DIRECTORY}")
    for name, data in (fixture.artifacts() if artifacts is None else artifacts).items():
        target = home.path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    bundle.files.write_atomic(
        safepaths.SafePath(home.path / defaults.NVIDIA_REPORT_NAME),
        json.dumps(report).encode(), mode=fixture.PRIVATE,
    )
    return home


def test_a_report_bound_to_the_image_the_lock_and_every_package_is_accepted(
    ports: portset.HostPorts, repository: safepaths.SourceRoot, root: safepaths.RuntimeRoot
) -> None:
    bundle = held(ports)
    fixture.write_lock(repository.path, bundle.files)
    lock = nvidialock.load(bundle, repository)
    home = output(bundle, root, fixture.report(IMAGE_ID))

    accepted = nvidialock.verify_report(bundle, root, home, frozen=FROZEN, lock=lock)

    assert accepted["status"] == "PASS" and accepted["image_id"] == f"sha256:{IMAGE_ID}"


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"status": "FAIL"}, refusals.RefusalReason.NVIDIA_REPORT_UNBOUND),
        ({"image_id": "sha256:" + "f" * 64}, refusals.RefusalReason.NVIDIA_REPORT_UNBOUND),
        ({"source_lock_sha256": "0" * 64}, refusals.RefusalReason.NVIDIA_REPORT_UNBOUND),
        ({"ready_to_install": True}, refusals.RefusalReason.NVIDIA_REPORT_UNBOUND),
        ({"hardware": "PASS"}, refusals.RefusalReason.NVIDIA_REPORT_UNBOUND),
        ({"kernel_release": "6.0"}, refusals.RefusalReason.NVIDIA_REPORT_UNBOUND),
    ],
)
def test_a_report_that_claims_more_or_names_another_input_is_unbound(
    ports: portset.HostPorts, repository: safepaths.SourceRoot, root: safepaths.RuntimeRoot,
    overrides: dict[str, object], reason: refusals.RefusalReason,
) -> None:
    bundle = held(ports)
    fixture.write_lock(repository.path, bundle.files)
    lock = nvidialock.load(bundle, repository)
    home = output(bundle, root, fixture.report(IMAGE_ID, **overrides))

    with pytest.raises(errors.Refusal) as refused:
        nvidialock.verify_report(bundle, root, home, frozen=FROZEN, lock=lock)

    assert refused.value.reason is reason


def test_the_artifacts_must_all_be_present_inside_the_output_with_the_reported_digests(
    ports: portset.HostPorts, repository: safepaths.SourceRoot, root: safepaths.RuntimeRoot
) -> None:
    bundle = held(ports)
    fixture.write_lock(repository.path, bundle.files)
    lock = nvidialock.load(bundle, repository)
    escaping = fixture.report(IMAGE_ID)
    assert isinstance(escaping["artifacts"], dict)
    escaping["artifacts"]["../outside"] = "0" * 64
    damaged = dict(fixture.artifacts())
    damaged[fixture.KMOD] = b"lost bytes"
    missing_lock = fixture.report(IMAGE_ID)
    assert isinstance(missing_lock["artifacts"], dict)
    del missing_lock["artifacts"][defaults.NVIDIA_LOCK_COPY]

    with pytest.raises(errors.Refusal) as escaped:
        nvidialock.verify_report(
            bundle, root, output(bundle, root, escaping), frozen=FROZEN, lock=lock
        )
    with pytest.raises(errors.Refusal) as mismatch:
        nvidialock.verify_report(
            bundle, root, output(bundle, root, fixture.report(IMAGE_ID), artifacts=damaged),
            frozen=FROZEN, lock=lock,
        )
    with pytest.raises(errors.Refusal) as incomplete:
        nvidialock.verify_report(
            bundle, root, output(bundle, root, missing_lock), frozen=FROZEN, lock=lock
        )

    assert escaped.value.reason is refusals.RefusalReason.NVIDIA_REPORT_UNBOUND
    assert mismatch.value.reason is refusals.RefusalReason.ARTIFACT_CHECKSUM_MISMATCH
    assert incomplete.value.reason is refusals.RefusalReason.NVIDIA_REPORT_UNBOUND


def test_the_package_set_must_be_the_lock_s_and_each_vendor_package_its_locked_bytes(
    ports: portset.HostPorts, repository: safepaths.SourceRoot, root: safepaths.RuntimeRoot
) -> None:
    bundle = held(ports)
    fixture.write_lock(repository.path, bundle.files)
    lock = nvidialock.load(bundle, repository)
    extra = dict(fixture.artifacts())
    extra["packages/stray-1-1.fc44.x86_64.rpm"] = b"a package nobody locked"
    with_extra = fixture.report(IMAGE_ID)
    with_extra["artifacts"] = {name: fixture.digest(data) for name, data in extra.items()}
    swapped = dict(fixture.artifacts())
    vendor = f"packages/nvidia-driver-{fixture.VERSION}-1.fc44.x86_64.rpm"
    swapped[vendor] = b"another vendor build"
    swapped_report = fixture.report(IMAGE_ID)
    swapped_report["artifacts"] = {name: fixture.digest(data) for name, data in swapped.items()}

    with pytest.raises(errors.Refusal) as stray:
        nvidialock.verify_report(
            bundle, root, output(bundle, root, with_extra, artifacts=extra),
            frozen=FROZEN, lock=lock,
        )
    with pytest.raises(errors.Refusal) as differs:
        nvidialock.verify_report(
            bundle, root, output(bundle, root, swapped_report, artifacts=swapped),
            frozen=FROZEN, lock=lock,
        )

    assert stray.value.reason is refusals.RefusalReason.NVIDIA_PACKAGES_INCOMPLETE
    assert differs.value.reason is refusals.RefusalReason.NVIDIA_PACKAGES_INCOMPLETE
    assert vendor in str(differs.value)
