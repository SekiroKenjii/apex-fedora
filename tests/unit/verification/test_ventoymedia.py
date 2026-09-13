"""The host side of the medium: the lock, the live bundle, the Ubuntu inputs, the binding."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest
import signedbundle
import ventoyinputs as inputs_support

from apex.adapters.fakes import fake_downloading
from apex.config import defaults
from apex.kernel import errors, identifiers, refusals, safepaths
from apex.ports import portset
from apex.provisioning.fixtures import ventoy_fixture
from apex.verification import ventoymedia

RUN = identifiers.RunId("1" * 32)


@pytest.fixture
def root(tmp_path: Path) -> safepaths.RuntimeRoot:
    base = tmp_path / "runtime"
    base.mkdir(mode=0o700)
    return safepaths.RuntimeRoot.adopt(base)


@pytest.fixture
def repository(tmp_path: Path) -> safepaths.SourceRoot:
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    inputs_support.write_lock(checkout)
    return safepaths.SourceRoot.adopt(checkout)


def held(
    root: safepaths.RuntimeRoot, *, gpgv: inputs_support.Gpgv | None = None
) -> tuple[portset.HostPorts, ventoymedia.Inputs]:
    ports = signedbundle.real_files_bundle()
    private, public = signedbundle.keys(ports, root)
    laid = inputs_support.lay_out(ports, root, private, public)
    ports = dataclasses.replace(
        ports, processes=gpgv or inputs_support.Gpgv(), downloads=inputs_support.fetcher()
    )
    return ports, ventoymedia.Inputs(**dataclasses.asdict(laid))


def test_the_lock_is_read_with_its_pins_and_a_malformed_one_is_refused(
    repository: safepaths.SourceRoot, tmp_path: Path
) -> None:
    ports = signedbundle.real_files_bundle()

    lock = ventoymedia.load_lock(ports, repository)
    (tmp_path / "empty").mkdir()
    with pytest.raises(errors.Refusal) as refused:
        ventoymedia.load_lock(ports, safepaths.SourceRoot.adopt(tmp_path / "empty"))

    assert lock.version == inputs_support.VERSION and lock.commit == inputs_support.COMMIT
    assert lock.archive_name == f"ventoy-{inputs_support.VERSION}-linux.tar.gz"
    assert lock.ubuntu_signer == inputs_support.SIGNER
    assert lock.digest.hex == inputs_support.digest(inputs_support.ARCHIVE)
    assert refused.value.reason is refusals.RefusalReason.VENTOY_LOCK_MALFORMED


def test_the_live_bundle_is_accepted_against_the_operator_s_key_and_its_iso_named(
    root: safepaths.RuntimeRoot,
) -> None:
    ports, inputs = held(root)

    verified, iso = ventoymedia.verify_live(ports, root, inputs)

    assert str(verified.digest) == inputs_support.SIGNED_DIGEST
    assert iso.path.read_bytes() == inputs_support.LIVE_ISO
    with pytest.raises(errors.Refusal) as outside:
        ventoymedia.verify_live(
            ports, root, dataclasses.replace(inputs, live_output=root.path.parent / "elsewhere")
        )
    assert outside.value.reason is refusals.RefusalReason.PATH_OUTSIDE_RUNTIME_ROOT


def test_the_ubuntu_image_is_accepted_against_the_signed_checksums_and_the_pinned_signer(
    root: safepaths.RuntimeRoot, repository: safepaths.SourceRoot
) -> None:
    ports, inputs = held(root)
    lock = ventoymedia.load_lock(ports, repository)

    report, iso = ventoymedia.verify_ubuntu(ports, root, RUN, inputs, lock)

    assert report["status"] == "PASS" and report["signer"] == inputs_support.SIGNER
    assert report["iso_sha256"] == inputs_support.digest(inputs_support.UBUNTU_ISO)
    assert iso.path == inputs.ubuntu
    gpgv = ports.processes
    assert isinstance(gpgv, inputs_support.Gpgv)
    assert gpgv.gpgv[0][:2] == ["gpgv", "--homedir"]
    assert gpgv.gpgv[0][2] == str(root.path / "exports" / str(RUN) / defaults.GPGV_HOME)
    assert gpgv.gpgv[0][3:] == [
        "--keyring", str(inputs.keyring), "--status-fd", "1", str(inputs.signature),
        str(inputs.checksums),
    ]
    assert (root.path / "exports" / str(RUN) / defaults.UBUNTU_SIGNATURE_LOG).is_file()
    written = json.loads(
        (root.path / "exports" / str(RUN) / defaults.UBUNTU_VERIFICATION_NAME).read_text()
    )
    assert written == report


def test_another_signer_a_wrong_checksum_line_or_a_different_image_are_refused(
    root: safepaths.RuntimeRoot, repository: safepaths.SourceRoot
) -> None:
    ports, inputs = held(root, gpgv=inputs_support.Gpgv("0" * 40))
    lock = ventoymedia.load_lock(ports, repository)
    with pytest.raises(errors.Refusal) as signer:
        ventoymedia.verify_ubuntu(ports, root, RUN, inputs, lock)
    trusted = dataclasses.replace(ports, processes=inputs_support.Gpgv())
    Path(inputs.checksums).write_bytes(
        f"{'0' * 64} *{inputs_support.UBUNTU_NAME}\n".encode()
    )
    with pytest.raises(errors.Refusal) as line:
        ventoymedia.verify_ubuntu(trusted, root, RUN, inputs, lock)
    pinned = inputs_support.digest(inputs_support.UBUNTU_ISO)
    Path(inputs.checksums).write_bytes(f"{pinned} *{inputs_support.UBUNTU_NAME}\n".encode())
    Path(inputs.ubuntu).write_bytes(b"another image")
    trusted.digests.forget()
    with pytest.raises(errors.Refusal) as image:
        ventoymedia.verify_ubuntu(trusted, root, RUN, inputs, lock)

    assert signer.value.reason is refusals.RefusalReason.UBUNTU_SIGNER_UNKNOWN
    assert line.value.reason is refusals.RefusalReason.DOWNLOAD_CHECKSUM_MISMATCH
    assert image.value.reason is refusals.RefusalReason.DOWNLOAD_CHECKSUM_MISMATCH


def test_the_release_is_fetched_at_its_pin_once_and_its_checksum_file_must_name_it(
    root: safepaths.RuntimeRoot, repository: safepaths.SourceRoot
) -> None:
    ports, _ = held(root)
    lock = ventoymedia.load_lock(ports, repository)

    archive, sums = ventoymedia.fetch_ventoy(ports, root, lock)
    again, _ = ventoymedia.fetch_ventoy(ports, root, lock)

    fetched = ports.downloads
    assert isinstance(fetched, fake_downloading.OfflineFetcher)
    assert fetched.fetched == [inputs_support.ARCHIVE_URL, inputs_support.SUMS_URL]
    assert archive == again and archive.path.read_bytes() == inputs_support.ARCHIVE
    assert archive.path.parent == root.path / defaults.VENTOY_INPUTS_DIRECTORY
    sums.path.write_bytes(b"0" * 64 + b"  something-else.tar.gz\n")
    ports.digests.forget()
    unpinned = dataclasses.replace(
        ports, downloads=fake_downloading.OfflineFetcher({inputs_support.SUMS_URL: b"x"})
    )
    with pytest.raises(errors.Refusal) as refused:
        ventoymedia.fetch_ventoy(unpinned, root, lock)
    assert refused.value.reason is refusals.RefusalReason.DOWNLOAD_CHECKSUM_MISMATCH


def test_prepare_writes_the_request_and_every_proof_under_the_run(
    root: safepaths.RuntimeRoot, repository: safepaths.SourceRoot
) -> None:
    ports, inputs = held(root)

    prepared = ventoymedia.prepare(ports, root, RUN, repository, inputs)

    assert prepared.request == ventoy_fixture.VentoyRequest(
        files={
            name: identifiers.Digest(value)
            for name, value in inputs_support.request_files().items()
        },
        version=inputs_support.VERSION,
    )
    assert prepared.request_document["ventoy_commit"] == inputs_support.COMMIT
    assert prepared.request_document["digest"] == inputs_support.SIGNED_DIGEST
    run_directory = root.path / "exports" / str(RUN)
    for name in (
        ventoy_fixture.REQUEST_NAME, defaults.LIVE_VERIFICATION_NAME,
        defaults.INPUTS_LOCK_NAME, defaults.UBUNTU_VERIFICATION_NAME,
    ):
        assert (run_directory / name).is_file(), name
    assert json.loads((run_directory / ventoy_fixture.REQUEST_NAME).read_text()) == (
        prepared.request_document
    )


def test_the_medium_is_bound_to_the_report_and_the_report_to_the_request(
    root: safepaths.RuntimeRoot, repository: safepaths.SourceRoot
) -> None:
    ports, inputs = held(root)
    prepared = ventoymedia.prepare(ports, root, RUN, repository, inputs)
    output = root.path / "exports" / str(RUN) / "output"
    output.mkdir()
    (output / ventoy_fixture.IMAGE).write_bytes(inputs_support.MEDIUM)
    remote = safepaths.RemotePath(f"/var/tmp/apex-{RUN}/ventoy")

    image, execution = ventoymedia.bind(
        ports, root, RUN, prepared, inputs_support.report(inputs_support.request_files()),
        remote=remote,
    )
    other = inputs_support.report({**inputs_support.request_files(), "Ubuntu.iso": "0" * 64})
    with pytest.raises(errors.Refusal) as answers:
        ventoymedia.bind(ports, root, RUN, prepared, other, remote=remote)
    (output / ventoy_fixture.IMAGE).write_bytes(b"not the medium reported")
    ports.digests.forget()
    with pytest.raises(errors.Refusal) as differs:
        ventoymedia.bind(
            ports, root, RUN, prepared, inputs_support.report(inputs_support.request_files()),
            remote=remote,
        )

    assert image.path == output / ventoy_fixture.IMAGE
    assert execution == {
        "status": "PASS", "remote": str(remote),
        "image_sha256": inputs_support.digest(inputs_support.MEDIUM),
        "boot_acceptance": "NOT TESTED", "physical_usb_written": False,
    }
    assert (root.path / "exports" / str(RUN) / defaults.VENTOY_SUMS_NAME).read_bytes() == (
        inputs_support.sums_text()
    )
    assert answers.value.reason is refusals.RefusalReason.FIXTURE_REPORT_MALFORMED
    assert differs.value.reason is refusals.RefusalReason.ARTIFACT_CHECKSUM_MISMATCH
