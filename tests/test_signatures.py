import json
import shutil
import subprocess
import pytest
from apexlib.common import Blocked, sha256
from apexlib.signatures import verify


@pytest.fixture
def signed(tmp_path):
    if not shutil.which('openssl'):
        pytest.skip('OpenSSL is required for signature tests')
    key, public = tmp_path / 'signing.key', tmp_path / 'trust.pub'
    output = tmp_path / 'output'
    output.mkdir()
    subprocess.run(['openssl', 'genpkey', '-algorithm', 'ED25519', '-out', str(key)], check=True)
    subprocess.run(['openssl', 'pkey', '-in', str(key), '-pubout', '-out', str(public)], check=True)
    artifact = output / 'payload.txt'
    artifact.write_text('frozen artifact')
    manifest = output / 'artifacts.json'
    manifest.write_text(json.dumps({'schema': 1, 'digest': 'sha256:' + 'a'*64, 'files': {'payload.txt': sha256(artifact)}}))
    subprocess.run(['openssl', 'pkeyutl', '-sign', '-rawin', '-inkey', str(key), '-in', str(manifest), '-out', str(output / 'artifacts.sig')], check=True)
    return output, public


def test_signature_accepts_trusted_key(signed):
    assert verify(*signed)['status'] == 'PASS'


def test_signature_rejects_changed_payload(signed):
    output, key = signed
    (output / 'payload.txt').write_text('tampered')
    with pytest.raises(Blocked, match='checksum'):
        verify(output, key)


def test_unsigned_extra_artifact_rejected(signed):
    output, key = signed
    (output / 'substitute.qcow2').write_bytes(b'unsigned')
    with pytest.raises(Blocked, match='unsigned'):
        verify(output, key)


def test_signature_rejects_changed_manifest(signed):
    output, key = signed
    (output / 'artifacts.json').write_text('{}')
    with pytest.raises(Blocked, match='signature'):
        verify(output, key)


def test_signature_rejects_wrong_key(signed, tmp_path):
    output, _ = signed
    key, public = tmp_path / 'wrong.key', tmp_path / 'wrong.pub'
    subprocess.run(['openssl', 'genpkey', '-algorithm', 'ED25519', '-out', str(key)], check=True)
    subprocess.run(['openssl', 'pkey', '-in', str(key), '-pubout', '-out', str(public)], check=True)
    with pytest.raises(Blocked, match='signature'):
        verify(output, public)


def test_bundled_key_is_not_independent_trust(signed):
    output, key = signed
    bundled = output / 'trust.pub'
    shutil.copyfile(key, bundled)
    with pytest.raises(Blocked, match='independently'):
        verify(output, bundled)


def test_signed_inventory_cannot_mislabel_oci_digest(signed, tmp_path):
    output, public = signed
    payload = output / 'payload-manifest.json'
    payload.write_text('{"schemaVersion": 2}')
    manifest = output / 'artifacts.json'
    data = json.loads(manifest.read_text())
    data['files']['payload-manifest.json'] = sha256(payload)
    manifest.write_text(json.dumps(data))
    subprocess.run(['openssl', 'pkeyutl', '-sign', '-rawin', '-inkey', str(tmp_path / 'signing.key'), '-in', str(manifest), '-out', str(output / 'artifacts.sig')], check=True)
    with pytest.raises(Blocked, match='packaged OCI'):
        verify(output, public)
