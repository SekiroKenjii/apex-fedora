#!/usr/bin/python3
"""Sign a frozen local payload using a VM-only development installer key."""
import importlib.util
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import re
import sys


def main():
    marker = Path('/etc/apex-builder')
    if os.geteuid() != 0 or not marker.is_file() or marker.read_text().strip() != 'apex-isolated-builder-v1':
        raise RuntimeError('Run only in the isolated Fedora builder')
    subprocess.run(['systemd-detect-virt', '--quiet', '--vm'], check=True)
    if len(sys.argv) != 2 or not re.fullmatch(r'/var/tmp/apex-[a-f0-9]{32}/output/apex-fedora\.oci\.tar', sys.argv[1]):
        raise RuntimeError('Use the frozen Fedora archive retained by the builder')
    archive = Path(sys.argv[1])
    if not archive.is_file() or archive.is_symlink() or archive.resolve() != archive:
        raise RuntimeError('Frozen archive must be a regular file')
    os.umask(0o077)
    spec = importlib.util.spec_from_file_location('preflight', Path(__file__).with_name('installer-preflight.py'))
    preflight = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(preflight)
    target = json.loads(Path('target-image.json').read_text())
    digest = target['digest']
    metadata = {'digest': digest, 'image_id': target['image_id'],
                'reference': 'localhost/apex-payload@' + digest,
                'identity': 'localhost/apex-payload:' + digest.removeprefix('sha256:'),
                'purpose': 'development-installer-only', 'public_key_sha256': '0' * 64}
    preflight.contract(metadata)
    source = 'oci-archive:' + str(archive)
    raw = subprocess.check_output(['skopeo', 'inspect', '--raw', source])
    if 'sha256:' + preflight.sha(raw) != digest or json.loads(raw)['config']['digest'] != target['image_id']:
        raise RuntimeError('Refuse to sign a changed payload')
    keydir = Path('/var/lib/apex/signing/installer-development')
    keydir.mkdir(parents=True, mode=0o700, exist_ok=True)
    prefix = keydir / 'payload'
    passphrase = keydir / 'passphrase'
    keyfiles = [keydir / 'payload.private', keydir / 'payload.pub', passphrase]
    if not any(p.exists() for p in keyfiles):
        passphrase.write_text(secrets.token_urlsafe(48) + '\n')
        subprocess.run(['skopeo', 'generate-sigstore-key', '--passphrase-file', passphrase,
                        '--output-prefix', prefix], check=True)
    if not all(p.is_file() and not p.is_symlink() and p.stat().st_mode & 0o077 == 0 for p in keyfiles):
        raise RuntimeError('Installer key is incomplete or has unsafe permissions; preserve it for review')
    public_key = keyfiles[1].read_bytes()
    metadata['public_key_sha256'] = preflight.sha(public_key)
    trust = Path('installer-trust')
    trust.mkdir(mode=0o700)
    (trust / 'payload.json').write_text(json.dumps(metadata, indent=2) + '\n')
    (trust / 'payload.pub').write_bytes(public_key)
    (trust / 'policy.json').write_text(json.dumps(preflight.signature_policy(metadata, public_key), indent=2) + '\n')
    work = Path('installer-signing').resolve()
    work.mkdir(mode=0o700)
    bootstrap = work / 'bootstrap.json'
    # Use the frozen compressed blobs; exporting an unpacked store can change them.
    bootstrap.write_text(json.dumps({'default': [{'type': 'reject'}], 'transports': {
        'oci-archive': {str(archive): [{'type': 'insecureAcceptAnything'}]}}}))
    signed = Path('installer-payload').resolve()
    subprocess.run(['skopeo', '--policy', bootstrap, 'copy', '--preserve-digests', '--dest-compress',
                    '--sign-by-sigstore-private-key', keyfiles[0], '--sign-passphrase-file', passphrase,
                    '--sign-identity', metadata['identity'], source, 'dir:' + str(signed)], check=True)
    checking = work / 'verify.json'
    checking.write_text(json.dumps(preflight.signature_policy(metadata, public_key, payload=signed)))
    result = preflight.verify(trust, checking, payload=signed)
    output = Path('output/installer/payload-trust')
    shutil.copytree(trust, output)
    (output / 'builder-verification.json').write_text(json.dumps(result, indent=2) + '\n')
    print('Frozen payload signature verified in builder; ISO boot remains NOT TESTED', flush=True)


if __name__ == '__main__':
    main()
