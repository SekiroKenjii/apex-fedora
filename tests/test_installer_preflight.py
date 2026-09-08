import importlib.util
import json
import os
import subprocess
import sys

import pytest
from apexlib.common import ROOT


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'guest' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


preflight = load('installer-preflight')
entrypoint = load('guard-installer-entrypoint')


@pytest.fixture
def fixture(tmp_path):
    config = b'{}'
    layer = b'synthetic compressed layer bytes'
    config_digest = 'sha256:' + preflight.sha(config)
    layer_digest = 'sha256:' + preflight.sha(layer)
    raw = json.dumps({'config': {'digest': config_digest, 'size': len(config)},
                      'layers': [{'digest': layer_digest, 'size': len(layer)}]}).encode()
    (tmp_path / config_digest[7:]).write_bytes(config)
    (tmp_path / layer_digest[7:]).write_bytes(layer)
    (tmp_path / 'manifest.json').write_bytes(raw)
    digest = 'sha256:' + preflight.sha(raw)
    key = b'synthetic public key for unit tests'
    metadata = {'digest': digest, 'image_id': config_digest,
                'reference': 'localhost/apex-payload@' + digest,
                'identity': 'localhost/apex-payload:' + digest[7:],
                'purpose': 'development-installer-only', 'public_key_sha256': preflight.sha(key)}
    (tmp_path / 'payload.json').write_text(json.dumps(metadata))
    (tmp_path / 'payload.pub').write_bytes(key)
    policy = preflight.signature_policy(metadata, key, payload=tmp_path)
    (tmp_path / 'policy.json').write_text(json.dumps(policy))
    return tmp_path, metadata, policy, raw


def test_preflight_requires_policy_verification_and_checks_manifest_twice(fixture, monkeypatch):
    folder, metadata, _, raw = fixture
    opened = []
    monkeypatch.setattr(preflight, 'verified_open', lambda *args: opened.append(args) or {'protocol': '0.2.8'})
    result = preflight.verify(folder, folder / 'policy.json', payload=folder)
    assert result['status'] == 'PASS' and result['digest'] == metadata['digest']
    assert opened == [('dir:' + str(folder), folder / 'policy.json')]
    assert result['verified_blob_count'] == 2
    assert result['verified_blob_bytes'] == sum(d['size'] for d in [json.loads(raw)['config'], *json.loads(raw)['layers']])


@pytest.mark.parametrize('field,value', [
    ('digest', 'latest'), ('image_id', 'sha256:bad'), ('purpose', 'release'),
    ('reference', 'docker://unexpected/image:latest'), ('identity', 'localhost/other:tag'),
    ('public_key_sha256', '0' * 64),
])
def test_invalid_contract_stops_before_container_operations(fixture, monkeypatch, field, value):
    folder, metadata, _, _ = fixture
    metadata[field] = value
    (folder / 'payload.json').write_text(json.dumps(metadata))
    monkeypatch.setattr(preflight.subprocess, 'run', lambda *a, **k: pytest.fail('No container command allowed'))
    with pytest.raises(ValueError):
        preflight.verify(folder, folder / 'policy.json', payload=folder)


def test_permissive_policy_cannot_replace_trust(fixture, monkeypatch):
    folder, _, _, _ = fixture
    (folder / 'policy.json').write_text(json.dumps({'default': [{'type': 'insecureAcceptAnything'}]}))
    monkeypatch.setattr(preflight.subprocess, 'run', lambda *a, **k: pytest.fail('No container command allowed'))
    with pytest.raises(ValueError, match='policy differs'):
        preflight.verify(folder, folder / 'policy.json', payload=folder)


@pytest.mark.parametrize('failure', ['changed-manifest', 'proxy-rejected', 'changed-source-after-verification'])
def test_preflight_fails_closed(fixture, monkeypatch, failure):
    folder, _, _, _ = fixture
    if failure == 'changed-manifest':
        (folder / 'manifest.json').write_bytes(b'{}')

    def opened(*args):
        if failure == 'proxy-rejected':
            raise RuntimeError('Signature rejected')
        if failure == 'changed-source-after-verification':
            (folder / 'manifest.json').write_bytes(b'{}')
        return {'protocol': '0.2.8'}

    monkeypatch.setattr(preflight, 'verified_open', opened)
    with pytest.raises((ValueError, RuntimeError)):
        preflight.verify(folder, folder / 'policy.json', payload=folder)


@pytest.mark.parametrize('fault', ['missing', 'same-size-corruption', 'truncated', 'symlink'])
def test_checks_every_blob_before_anaconda(fixture, monkeypatch, fault):
    folder, _, _, raw = fixture
    blob = folder / json.loads(raw)['layers'][0]['digest'][7:]
    if fault == 'missing':
        blob.unlink()
    elif fault == 'symlink':
        blob.unlink()
        blob.symlink_to(folder / 'manifest.json')
    elif fault == 'same-size-corruption':
        blob.write_bytes(b'x' * blob.stat().st_size)
    else:
        blob.write_bytes(b'x')
    monkeypatch.setattr(preflight, 'verified_open', lambda *a: {'protocol': '0.2.8'})
    with pytest.raises(ValueError, match='blob'):
        preflight.verify(folder, folder / 'policy.json', payload=folder)


@pytest.mark.parametrize('reply', [b'{}', b'[]', b'null', b'{"success":false,"error":"bad signature"}',
                                   b'{"success":1,"pipeid":0}', b'{"success":true,"pipeid":1}'])
def test_proxy_rejects_invalid_or_failed_replies(reply):
    with pytest.raises(RuntimeError):
        preflight.proxy_reply(reply)


@pytest.mark.parametrize('fault', ['none', 'version', 'policy', 'zero-handle', 'invalid-json', 'oversized', 'pipe', 'close', 'exit'])
def test_proxy_socket_lifecycle(tmp_path, monkeypatch, fault):
    real_popen = subprocess.Popen
    processes = []
    server = '''
import json, socket, sys
channel = socket.socket(fileno=int(sys.argv[1]))
fault = sys.argv[2]
for method in ('Initialize', 'OpenImage', 'CloseImage', 'Shutdown'):
    request = json.loads(channel.recv(32768))
    if request['method'] == 'Shutdown':
        break
    assert request['method'] == method
    value = {'Initialize': '0.2.8', 'OpenImage': 1, 'CloseImage': None}[method]
    reply = {'success': True, 'value': value, 'pipeid': 0, 'error': ''}
    if method == 'Initialize' and fault == 'version': reply['value'] = '0.3.0'
    if method == 'OpenImage':
        if fault == 'exit': sys.exit(1)
        if fault == 'policy': reply.update(success=False, error='bad signature')
        if fault == 'zero-handle': reply['value'] = 0
        if fault == 'pipe': reply['pipeid'] = 1
        if fault == 'invalid-json':
            channel.send(b'bad json'); continue
        if fault == 'oversized':
            channel.send(b'x' * 40000); continue
    if method == 'CloseImage' and fault == 'close': reply['value'] = 7
    channel.send(json.dumps(reply).encode())
channel.close()
'''

    def spawn(args, **kwargs):
        assert args[:3] == ['skopeo', '--policy', str(tmp_path / 'policy.json')]
        assert args[3:5] == ['experimental-image-proxy', '--sockfd']
        assert kwargs['pass_fds'] == (int(args[5]),)
        process = real_popen([sys.executable, '-c', server, args[5], fault], **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(subprocess, 'Popen', spawn)
    before = len(os.listdir('/proc/self/fd'))
    if fault == 'none':
        result = preflight.verified_open('dir:/fixture', tmp_path / 'policy.json')
        assert result['protocol'] == '0.2.8' and result['method'] == 'OpenImage'
    else:
        with pytest.raises((RuntimeError, ValueError)):
            preflight.verified_open('dir:/fixture', tmp_path / 'policy.json')
    assert len(processes) == 1 and processes[0].poll() is not None
    assert len(os.listdir('/proc/self/fd')) == before


def test_entrypoint_blocks_upstream_on_verification_error(monkeypatch):
    def fail(*args, **kwargs):
        assert kwargs == {'check': True}
        raise subprocess.CalledProcessError(1, args[0])
    monkeypatch.setattr(subprocess, 'run', fail)
    namespace = {'events': []}
    with pytest.raises(subprocess.CalledProcessError):
        exec(entrypoint.guarded('#!/usr/bin/python3\nevents.append("upstream started")\n'), namespace)
    assert namespace['events'] == []


def test_entrypoint_starts_upstream_only_after_verification(monkeypatch):
    events = []
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: events.append('verified'))
    exec(entrypoint.guarded('#!/usr/bin/python3\nevents.append("upstream started")\n'), {'events': events})
    assert events == ['verified', 'upstream started']


@pytest.mark.parametrize('source', ['#!/bin/bash\n', '#!/usr/bin/python3\nfrom __future__ import annotations\n', '#!/usr/bin/python3\n# apex-installer-preflight\n'])
def test_entrypoint_changes_need_review(source):
    with pytest.raises(ValueError):
        entrypoint.guarded(source)


@pytest.mark.parametrize('script,message', [
    ('installer-preflight.py', 'Apex installer environment'),
    ('sign-installer-payload.py', 'isolated Fedora builder'),
    ('guard-installer-entrypoint.py', 'constructing the installer image'),
])
def test_guest_tools_refuse_host(script, message):
    result = subprocess.run([sys.executable, ROOT / 'guest' / script], capture_output=True, text=True)
    assert result.returncode != 0 and message in result.stderr
