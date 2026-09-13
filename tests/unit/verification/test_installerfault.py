"""The host side of the installer payload fault: the request, the confirmation, the result."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import installerruns
import pytest

from apex.adapters.fakes import fake_files
from apex.config import defaults
from apex.kernel import errors, identifiers, refusals, safepaths, verdicts
from apex.ports import portset
from apex.provisioning import comparing
from apex.verification import installerfault

RUN = identifiers.RunId("e" * 32)


@pytest.fixture
def root(tmp_path: Path) -> safepaths.RuntimeRoot:
    base = tmp_path / "runtime"
    base.mkdir(mode=0o700)
    return safepaths.RuntimeRoot.adopt(base)


def held(ports: portset.HostPorts) -> portset.HostPorts:
    return dataclasses.replace(ports, files=fake_files.MemoryFiles())


def observation(source: str, overlay: str, *, unchanged: bool = True) -> comparing.DiskObservation:
    return comparing.DiskObservation(
        source=safepaths.SafePath(Path(source)), overlay=safepaths.SafePath(Path(overlay)),
        unchanged=unchanged, output="",
    )


def comparison(*unchanged: bool) -> comparing.RunComparison:
    return comparing.RunComparison(
        disks=tuple(
            observation(f"/s/{index}", f"/o/{index}", unchanged=flag)
            for index, flag in enumerate(unchanged)
        ),
        variables_unchanged=True,
    )


def test_the_request_names_the_case_the_image_and_the_machine_and_reads_back_the_same() -> None:
    request = installerfault.Request(
        case="wrong-key", image=identifiers.Digest("a" * 64), process=4242, run=RUN
    )

    document = request.document()

    assert document == {
        "schema": 1, "case": "wrong-key", "iso_sha256": "a" * 64, "vm_pid": 4242, "run": str(RUN),
    }
    assert installerfault.Request.parse(json.loads(json.dumps(document))) == request
    with pytest.raises(errors.Refusal) as malformed:
        installerfault.Request.parse({"case": "wrong-key"})
    assert malformed.value.reason is refusals.RefusalReason.LEASE_MALFORMED


@pytest.mark.parametrize(
    ("case", "key", "reason"),
    [
        ("wrong-key", None, refusals.RefusalReason.REQUEST_MALFORMED),
        (
            "corrupt-blob", "-----BEGIN PUBLIC KEY-----\nx\n",
            refusals.RefusalReason.REQUEST_MALFORMED,
        ),
        ("no-such-case", None, refusals.RefusalReason.UNIT_UNKNOWN),
    ],
)
def test_only_the_wrong_key_case_takes_a_key_and_it_always_does(
    case: str, key: str | None, reason: refusals.RefusalReason
) -> None:
    with pytest.raises(errors.Refusal) as refused:
        installerfault.require_pairing(case, key)

    assert refused.value.reason is reason
    installerfault.require_pairing("wrong-key", "-----BEGIN PUBLIC KEY-----\nx\n")
    installerfault.require_pairing("corrupt-blob", None)


def test_a_key_is_read_from_inside_the_root_and_must_be_a_small_public_key_block(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    bundle = held(ports)
    public = root.path / "wrong.pub"
    public.write_bytes(b"")
    bundle.files.write_atomic(
        safepaths.SafePath(public), b"-----BEGIN PUBLIC KEY-----\nfixture\n",
        mode=defaults.RECORD_MODE,
    )
    certificate = root.path / "wrong.crt"
    certificate.write_bytes(b"")
    bundle.files.write_atomic(
        safepaths.SafePath(certificate), b"-----BEGIN CERTIFICATE-----\nnot a key\n",
        mode=defaults.RECORD_MODE,
    )
    large = root.path / "large.pub"
    large.write_bytes(b"")
    bundle.files.write_atomic(
        safepaths.SafePath(large), b"-----BEGIN PUBLIC KEY-----\n" + b"x" * 4096,
        mode=defaults.RECORD_MODE,
    )

    assert installerfault.read_key(bundle, root, public) == "-----BEGIN PUBLIC KEY-----\nfixture\n"
    for path in (certificate, large):
        with pytest.raises(errors.Refusal) as refused:
            installerfault.read_key(bundle, root, path)
        assert refused.value.reason is refusals.RefusalReason.PUBLIC_KEY_MALFORMED
    with pytest.raises(errors.Refusal):
        installerfault.read_key(bundle, root, root.path.parent / "outside.pub")


@pytest.mark.parametrize(
    "broken",
    [
        {"case": "wrong-key"},
        {"status": "FAIL"},
        {"returncode": 0},
        {"preflight": {"status": "PASS"}},
        {"preflight": None},
        {"upstream_log_created": True},
        {"selinux_after": "Permissive"},
    ],
)
def test_the_report_is_confirmed_only_when_every_field_says_what_a_pass_must(
    broken: dict[str, object],
) -> None:
    assert installerfault.confirmed(installerruns.confirming(), installerruns.CASE)
    assert not installerfault.confirmed(
        {**installerruns.confirming(), **broken}, installerruns.CASE
    )


def prepared(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot, *, guest: dict[str, object] | None = None
) -> tuple[portset.HostPorts, safepaths.SafePath, installerfault.Request]:
    bundle = held(ports)
    run_directory = root.child(f"vm-runs/{RUN}")
    iso = installerruns.record(bundle, root, run_directory)
    request = installerfault.Request(
        case=installerruns.CASE,
        image=bundle.digests.file(safepaths.SafePath.regular_file(iso, within=root)),
        process=4242,
        run=RUN,
    )
    installerfault.write_request(bundle, run_directory, request)
    installerfault.write_kept(
        bundle, run_directory, request=request,
        observations=installerruns.confirming() if guest is None else guest,  # type: ignore[arg-type]
    )
    return bundle, run_directory, request


def test_a_confirmed_report_over_two_unchanged_disks_passes_and_the_result_is_the_proof(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    bundle, run_directory, request = prepared(ports, root)

    result = installerfault.collect(
        bundle, root=root, run_directory=run_directory, comparison=comparison(True, True)
    )

    assert result.verdict is verdicts.PASSED and result.case == installerruns.CASE
    assert result.image == request.image
    assert result.proof.path == run_directory.path / defaults.FAULT_RESULT_NAME
    written = json.loads(bundle.files.read_bytes(result.proof, limit=1 << 20))
    assert written["status"] == "PASS" and written["iso_sha256"] == request.image.hex
    assert written["guest"]["request"]["case"] == installerruns.CASE
    assert [item["unchanged"] for item in written["disk_comparison"]["disks"]] == [True, True]
    assert result.document()["proof"] == str(result.proof)


def test_a_changed_disk_writes_a_failed_result_and_is_refused_by_name(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    bundle, run_directory, _ = prepared(ports, root)

    with pytest.raises(errors.Refusal) as refused:
        installerfault.collect(
            bundle, root=root, run_directory=run_directory, comparison=comparison(True, False)
        )

    assert refused.value.reason is refusals.RefusalReason.FAULT_DISK_CHANGED
    proof = safepaths.SafePath(run_directory.path / defaults.FAULT_RESULT_NAME)
    assert json.loads(bundle.files.read_bytes(proof, limit=1 << 20))["status"] == "FAIL"


def test_one_disk_is_not_the_two_the_fault_names(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    bundle, run_directory, _ = prepared(ports, root)

    with pytest.raises(errors.Refusal) as refused:
        installerfault.collect(
            bundle, root=root, run_directory=run_directory, comparison=comparison(True)
        )

    assert refused.value.reason is refusals.RefusalReason.FAULT_DISK_CHANGED


def test_a_report_that_does_not_confirm_the_rejection_stops_before_the_disks_are_judged(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    bundle, run_directory, _ = prepared(
        ports, root, guest={**installerruns.confirming(), "returncode": 0}
    )

    with pytest.raises(errors.Refusal) as refused:
        installerfault.collect(
            bundle, root=root, run_directory=run_directory, comparison=comparison(True, True)
        )

    assert refused.value.reason is refusals.RefusalReason.FAULT_NOT_CONFIRMED
    assert not bundle.files.exists(
        safepaths.SafePath(run_directory.path / defaults.FAULT_RESULT_NAME)
    )


def test_an_image_that_changed_since_the_request_is_refused(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    bundle, run_directory, _ = prepared(ports, root)
    (root.path / installerruns.ISO_NAME).write_bytes(b"a different image, rebuilt since")

    with pytest.raises(errors.Refusal) as refused:
        installerfault.collect(
            bundle, root=root, run_directory=run_directory, comparison=comparison(True, True)
        )

    assert refused.value.reason is refusals.RefusalReason.SOURCE_IMAGE_CHANGED


def test_a_run_without_a_request_is_refused_by_the_missing_record(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    bundle = held(ports)

    with pytest.raises(errors.Refusal) as refused:
        installerfault.collect(
            bundle, root=root, run_directory=root.child(f"vm-runs/{RUN}"),
            comparison=comparison(True, True),
        )

    assert refused.value.reason is refusals.RefusalReason.PATH_NOT_A_REGULAR_FILE
