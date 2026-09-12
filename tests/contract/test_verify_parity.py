"""The new verifier and the older `verify` agree on every case the older tests pin.

Both read the same openssl-signed fixture. Where the older verifier raises, the new one refuses;
where it accepts, the new one accepts and reports the same digest.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from apex.adapters.fakes import (
    fake_clock,
    fake_guestshell,
    fake_hypervisor,
    fake_ids,
    fake_locking,
    fake_process,
    fake_qmp,
)
from apex.adapters.real import (
    real_archives,
    real_digesting,
    real_downloading,
    real_files,
    real_signing,
)
from apex.kernel import errors, hashing, safepaths
from apex.ports import portset
from apex.trust import anchors, verifying
from apexlib.common import Blocked
from apexlib.signatures import verify as older_verify

pytestmark = pytest.mark.skipif(shutil.which("openssl") is None, reason="NOT TESTED: no openssl")


def ports() -> portset.HostPorts:
    return portset.HostPorts(
        processes=fake_process.ScriptedProcess(),
        files=real_files.LocalFiles(),
        clock=fake_clock.ManualClock(),
        identities=fake_ids.SequenceIdentities(),
        locks=fake_locking.MemoryLocks(),
        digests=real_digesting.CachedDigests(),
        archives=real_archives.TarArchives(),
        signing=real_signing.OpensslSigner(),
        downloads=real_downloading.CurlDownloads(),
        hypervisor=fake_hypervisor.FakeQemu(),
        monitor=fake_qmp.ScriptedQmp(),
        guest=fake_guestshell.ScriptedGuest(),
    )


def openssl(*arguments: str) -> None:
    subprocess.run(["openssl", *arguments], check=True, capture_output=True)


@pytest.fixture
def fixture(tmp_path: Path) -> tuple[safepaths.RuntimeRoot, Path, Path]:
    base = tmp_path / "runtime"
    base.mkdir(mode=0o700)
    keys = tmp_path / "keys"
    keys.mkdir()
    private, public = keys / "signing.key", keys / "trust.pub"
    openssl("genpkey", "-algorithm", "ED25519", "-out", str(private))
    openssl("pkey", "-in", str(private), "-pubout", "-out", str(public))
    output = base / "output"
    output.mkdir()
    artifact = output / "payload.txt"
    artifact.write_text("frozen artifact")
    manifest = output / "artifacts.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": 1,
                "digest": "sha256:" + "a" * 64,
                "files": {"payload.txt": hashing.digest_bytes(artifact.read_bytes()).hex},
            }
        )
    )
    openssl(
        "pkeyutl", "-sign", "-rawin", "-inkey", str(private), "-in", str(manifest),
        "-out", str(output / "artifacts.sig"),
    )
    return safepaths.RuntimeRoot.adopt(base), output, public


def both(root: safepaths.RuntimeRoot, output: Path, key: Path) -> tuple[bool, bool]:
    try:
        older_verify(output, key)
        older = True
    except Blocked:
        older = False
    try:
        verifying.verify_bundle(
            ports(),
            location=verifying.BundleLocation(root=root, relative="output"),
            anchor=anchors.operator_supplied(key),
        )
        newer = True
    except errors.Refusal:
        newer = False
    return older, newer


def test_both_accept_the_untouched_bundle(
    fixture: tuple[safepaths.RuntimeRoot, Path, Path],
) -> None:
    assert both(*fixture) == (True, True)


def test_both_refuse_a_changed_payload(fixture: tuple[safepaths.RuntimeRoot, Path, Path]) -> None:
    root, output, key = fixture
    (output / "payload.txt").write_text("tampered")

    assert both(root, output, key) == (False, False)


def test_both_refuse_an_unsigned_extra(fixture: tuple[safepaths.RuntimeRoot, Path, Path]) -> None:
    root, output, key = fixture
    (output / "substitute.qcow2").write_bytes(b"unsigned")

    assert both(root, output, key) == (False, False)


def test_both_refuse_a_changed_inventory(fixture: tuple[safepaths.RuntimeRoot, Path, Path]) -> None:
    root, output, key = fixture
    (output / "artifacts.json").write_text("{}")

    assert both(root, output, key) == (False, False)


def test_both_refuse_a_wrong_key(
    fixture: tuple[safepaths.RuntimeRoot, Path, Path], tmp_path: Path
) -> None:
    root, output, _ = fixture
    wrong, public = tmp_path / "wrong.key", tmp_path / "wrong.pub"
    openssl("genpkey", "-algorithm", "ED25519", "-out", str(wrong))
    openssl("pkey", "-in", str(wrong), "-pubout", "-out", str(public))

    assert both(root, output, public) == (False, False)


def test_both_refuse_a_bundled_key(fixture: tuple[safepaths.RuntimeRoot, Path, Path]) -> None:
    root, output, key = fixture
    shipped = output / "trust.pub"
    shutil.copyfile(key, shipped)

    assert both(root, output, shipped) == (False, False)
