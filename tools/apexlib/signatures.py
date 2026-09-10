from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess
import uuid

from .common import Blocked, atomic_json, regular_file, sha256


def trust_builder(directory: Path) -> dict:
    from .vm import ssh_args
    # Get the public key over the builder's authenticated SSH channel, not from a bundle.
    command = "test -f /etc/apex-builder && sudo openssl pkey -in /var/lib/apex/signing/local-dev.key -pubout"
    result = subprocess.run(ssh_args(directory) + [command], capture_output=True, check=True)
    subprocess.run(['openssl', 'pkey', '-pubin', '-noout'], input=result.stdout, capture_output=True, check=True)
    trust = directory / 'trust'
    trust.mkdir(mode=0o700, exist_ok=True)
    key = trust / 'development.pub'
    if key.exists() and key.read_bytes() != result.stdout:
        raise Blocked('Builder development key changed; review rotation before replacing trust')
    key.write_bytes(result.stdout)
    key.chmod(0o600)
    record = {'purpose': 'local-development-only', 'path': str(key), 'sha256': sha256(key), 'source': 'authenticated builder SSH; not the artifact bundle', 'release_trust': False}
    atomic_json(trust / 'development.json', record)
    return record


def exercise(directory: Path, trusted_key: Path, state: Path) -> Path:
    accepted = verify(directory, trusted_key)
    tests = state / 'signature-tests' / uuid.uuid4().hex
    tests.mkdir(parents=True, mode=0o700)
    results = {'valid_bundle': 'PASS'}

    def rejected(name, bundle, key, reason):
        try:
            verify(bundle, key)
        except Blocked as exc:
            if reason not in str(exc):
                raise Blocked(f'{name} failed for the wrong reason: {exc}') from exc
            results[name] = 'PASS'
        else:
            raise Blocked(f'{name}: verifier accepted invalid input')

    def headers(name):
        case = tests / name
        case.mkdir(mode=0o700)
        for filename in ('artifacts.json', 'artifacts.sig'):
            shutil.copyfile(directory / filename, case / filename)
        return case

    malformed = headers('changed-manifest')
    original = (malformed / 'artifacts.json').read_bytes()
    (malformed / 'artifacts.json').write_bytes(b'X' + original[1:])
    rejected('changed_manifest', malformed, trusted_key, 'signature rejected')
    tampered = headers('changed-payload')
    first = next(iter(json.loads((directory / 'artifacts.json').read_text())['files']))
    payload = tampered / first
    payload.parent.mkdir(parents=True, exist_ok=True)
    payload.write_bytes(b'intentionally invalid test payload')
    rejected('changed_payload', tampered, trusted_key, 'checksum mismatch')
    wrong, public = tests / 'wrong.key', tests / 'wrong.pub'
    subprocess.run(['openssl', 'genpkey', '-algorithm', 'ED25519', '-out', str(wrong)], check=True)
    wrong.chmod(0o600)
    subprocess.run(['openssl', 'pkey', '-in', str(wrong), '-pubout', '-out', str(public)], check=True)
    rejected('untrusted_key', directory, public, 'signature rejected')
    rejected('bundle_cannot_establish_trust', directory, directory / 'development-signing.pub', 'independently trusted')
    proof = tests / 'results.json'
    atomic_json(proof, {'digest': accepted['digest'], 'status': 'PASS', 'checks': results, 'accepted_bundle': accepted, 'bootc_updates': 'NOT TESTED'})
    return proof


def verify(directory: Path, trusted_key: Path) -> dict:
    directory = directory.resolve()
    key = regular_file(trusted_key)
    if key.is_relative_to(directory):
        raise Blocked('Select an independently trusted key, not the key supplied with the artifact')
    manifest = regular_file(directory / 'artifacts.json', within=directory)
    signature = regular_file(directory / 'artifacts.sig', within=directory)
    result = subprocess.run(['openssl', 'pkeyutl', '-verify', '-rawin', '-pubin', '-inkey', str(key), '-in', str(manifest), '-sigfile', str(signature)], capture_output=True)
    if result.returncode:
        raise Blocked('Artifact signature rejected')
    data = json.loads(manifest.read_text())
    if data.get('schema') != 1 or not re.fullmatch(r'sha256:[a-f0-9]{64}', data.get('digest', '')) or not data.get('files'):
        raise Blocked('Invalid signed artifact manifest')
    allowed = set(data['files']) | {'artifacts.json', 'artifacts.sig', 'development-signing.pub'}
    for path in directory.rglob('*'):
        if path.is_symlink() or (path.is_file() and str(path.relative_to(directory)) not in allowed):
            raise Blocked('Artifact directory contains unsigned or linked content')
    for name, expected in data['files'].items():
        path = regular_file(directory / name, within=directory)
        if sha256(path) != expected:
            raise Blocked(f'Artifact checksum mismatch: {name}')
    for name in ('manifest.json', 'payload-manifest.json'):
        if name in data['files'] and 'sha256:' + sha256(directory / name) != data['digest']:
            raise Blocked('Signed digest does not match the packaged OCI manifest')
    if 'image.json' in data['files']:
        target = json.loads((directory / 'image.json').read_text())
        if target.get('digest') != data['digest']:
            raise Blocked('Signed image metadata names a different digest')
        if 'manifest.json' not in data['files'] or json.loads((directory / 'manifest.json').read_text()).get('config', {}).get('digest') != target.get('image_id'):
            raise Blocked('Image metadata does not match the OCI configuration')
    return {'status': 'PASS', 'digest': data['digest'], 'purpose': data.get('purpose'), 'trusted_key_sha256': sha256(key), 'files_verified': len(data['files']), 'bootc_update_policy': 'NOT TESTED'}
