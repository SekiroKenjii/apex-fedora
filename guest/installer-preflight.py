#!/usr/bin/python3
"""Verify the bundled image before any Anaconda code runs."""
import base64
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import time

TRUST = Path('/usr/share/apex/installer-trust')
PAYLOAD = Path('/usr/share/apex/payload')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def contract(metadata):
    for field in ('digest', 'image_id'):
        if not re.fullmatch(r'sha256:[a-f0-9]{64}', metadata.get(field, '')):
            raise ValueError(f'Invalid payload {field}')
    if metadata.get('purpose') != 'development-installer-only':
        raise ValueError('Unreviewed installer trust purpose')
    digest = metadata['digest']
    if metadata.get('reference') != 'localhost/apex-payload@' + digest:
        raise ValueError('Unexpected payload source')
    if metadata.get('identity') != 'localhost/apex-payload:' + digest[7:]:
        raise ValueError('Unexpected signature identity')
    if not re.fullmatch('[a-f0-9]{64}', metadata.get('public_key_sha256', '')):
        raise ValueError('Invalid payload public key checksum')


def signature_policy(metadata, public_key, *, payload=PAYLOAD):
    contract(metadata)
    if sha(public_key) != metadata['public_key_sha256']:
        raise ValueError('Payload public key checksum mismatch')
    requirement = {'type': 'sigstoreSigned', 'keyData': base64.b64encode(public_key).decode(),
                   'signedIdentity': {'type': 'exactReference', 'dockerReference': metadata['identity']}}
    return {'default': [{'type': 'reject'}], 'transports': {'dir': {str(payload): [requirement]}}}


def proxy_reply(raw):
    reply = json.loads(raw)
    if not isinstance(reply, dict) or reply.get('success') is not True:
        raise RuntimeError(f'Signature proxy rejected request: {reply}')
    if reply.get('pipeid') != 0:
        raise RuntimeError('Unexpected data pipe from signature proxy')
    return reply.get('value')


def verified_open(source, policy_path):
    # This is the same OpenImage policy check used by bootc, without fetching layers.
    # Pin the experimental protocol and fail if an upgrade changes the contract.
    parent, child = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
    parent.settimeout(30)
    with tempfile.TemporaryFile() as errors:
        process = None
        verified = False
        try:
            process = subprocess.Popen(['skopeo', '--policy', str(policy_path),
                                        'experimental-image-proxy', '--sockfd', str(child.fileno())],
                                       pass_fds=(child.fileno(),), stdin=subprocess.DEVNULL,
                                       stdout=subprocess.DEVNULL, stderr=errors)
            child.close()

            def call(method, args):
                packet = json.dumps({'method': method, 'args': args}).encode()
                if parent.send(packet) != len(packet):
                    raise RuntimeError('Incomplete signature proxy request')
                raw = parent.recv(32769)
                if not raw or len(raw) > 32768:
                    raise RuntimeError('Invalid signature proxy packet size')
                return proxy_reply(raw)

            protocol = call('Initialize', [])
            if protocol != '0.2.8':
                raise RuntimeError(f'Review signature proxy protocol {protocol!r}')
            image = call('OpenImage', [source])
            if type(image) is not int or image <= 0:
                raise RuntimeError('Signature proxy returned no verified image')
            if call('CloseImage', [image]) is not None:
                raise RuntimeError('Invalid CloseImage reply')
            verified = True
            return {'protocol': protocol, 'method': 'OpenImage', 'source': source}
        finally:
            child.close()
            if process is not None:
                try:
                    parent.send(json.dumps({'method': 'Shutdown', 'args': []}).encode())
                except OSError:
                    pass
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
            parent.close()
            if verified and process.returncode != 0:
                errors.seek(0)
                raise RuntimeError('Signature proxy shutdown failed: ' + errors.read(4096).decode(errors='replace'))


def verify(trust, policy_path, *, payload=PAYLOAD):
    metadata = json.loads((trust / 'payload.json').read_text())
    public_key = (trust / 'payload.pub').read_bytes()
    expected = signature_policy(metadata, public_key, payload=payload)
    if json.loads(policy_path.read_text()) != expected:
        raise ValueError('Installer container policy differs from the frozen trust contract')
    if not payload.is_absolute() or payload.resolve() != payload or not payload.is_dir():
        raise ValueError('Payload must be an absolute directory without symlinks')
    source = 'dir:' + str(payload)
    def manifest():
        path = payload / 'manifest.json'
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 4 * 1024 * 1024:
            raise ValueError('Invalid bundled manifest file')
        raw = path.read_bytes()
        if 'sha256:' + sha(raw) != metadata['digest']:
            raise ValueError('Bundled manifest digest changed')
        if json.loads(raw).get('config', {}).get('digest') != metadata['image_id']:
            raise ValueError('Bundled image configuration changed')
        return json.loads(raw)

    selected = manifest()
    verification = verified_open(source, policy_path)
    descriptors = [selected['config'], *selected['layers']]
    for descriptor in descriptors:
        digest = descriptor.get('digest', '')
        size = descriptor.get('size')
        if not re.fullmatch('sha256:[a-f0-9]{64}', digest) or type(size) is not int or size < 0:
            raise ValueError('Invalid bundled blob descriptor')
        path = payload / digest[7:]
        if path.is_symlink() or not path.is_file() or path.stat().st_size != size:
            raise ValueError(f'Bundled blob missing or changed size: {digest}')
        with path.open('rb') as stream:
            if 'sha256:' + hashlib.file_digest(stream, 'sha256').hexdigest() != digest:
                raise ValueError(f'Bundled blob checksum mismatch: {digest}')
    manifest()
    return {'status': 'PASS', 'digest': metadata['digest'], 'image_id': metadata['image_id'],
            'public_key_sha256': metadata['public_key_sha256'], 'verification': verification,
            'verified_blob_count': len(descriptors), 'verified_blob_bytes': sum(d['size'] for d in descriptors)}


def main():
    if os.geteuid() != 0 or not (TRUST / 'payload.json').is_file():
        raise RuntimeError('Run only in the Apex installer environment')
    if Path('/sys/fs/selinux/enforce').read_text().strip() != '1':
        raise RuntimeError('Installer requires SELinux enforcing')
    if not PAYLOAD.is_dir():
        raise RuntimeError('Bundled compressed payload is missing')
    runtime = Path('/run/apex')
    runtime.mkdir(mode=0o700, exist_ok=True)
    with (runtime / 'installer-preflight.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        result = {'status': 'FAIL'}
        started = time.monotonic()
        try:
            print('Apex: verifying bundled image before starting Anaconda', flush=True)
            result = verify(TRUST, Path('/etc/containers/policy.json'))
        except Exception as exc:
            result['error'] = str(exc)
            raise
        finally:
            result['duration_seconds'] = round(time.monotonic() - started, 3)
            temporary = runtime / 'installer-preflight.tmp'
            temporary.write_text(json.dumps(result, indent=2) + '\n')
            temporary.replace(runtime / 'installer-preflight.json')
        print('Apex: bundled image verified; starting Anaconda', flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'Apex: installation blocked before Anaconda: {exc}', file=sys.stderr, flush=True)
        sys.exit(1)
