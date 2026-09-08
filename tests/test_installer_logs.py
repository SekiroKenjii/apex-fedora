import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from apexlib import installerlogs
from apexlib.common import ROOT, Blocked

TOKEN = 'a' * 32


def frames(bundle=None):
    raw = json.dumps(bundle or {'schema': 1, 'token': TOKEN}).encode()
    encoded = base64.b64encode(raw).decode()
    chunks = [encoded[n:n + 768] for n in range(0, len(encoded), 768)]
    lines = [f'APEXLOG:{TOKEN}:{n}:{chunk}\r\n'.encode() for n, chunk in enumerate(chunks)]
    return lines + [f'APEXEND:{TOKEN}:{len(chunks)}:{hashlib.sha256(raw).hexdigest()}\r\n'.encode()]


def test_serial_transport_ignores_unrelated_lines_but_binds_token():
    lines = frames()
    lines.insert(1, b'[ 123.456] unrelated kernel message\r\n')
    lines.insert(0, f'APEXLOG:{"b" * 32}:0:ignored\r\n'.encode())
    assert installerlogs.decode(lines, TOKEN)['token'] == TOKEN


@pytest.mark.parametrize('fault', ['missing', 'duplicate', 'checksum', 'wrong-token', 'count', 'trailer', 'after-end'])
def test_serial_transport_rejects_damaged_capture(fault):
    lines = frames()
    if fault == 'missing':
        lines.pop(0)
    elif fault == 'duplicate':
        lines.insert(0, lines[0])
    elif fault == 'checksum':
        lines[-1] = f'APEXEND:{TOKEN}:1:{"0" * 64}\n'.encode()
    elif fault == 'wrong-token':
        lines = frames({'schema': 1, 'token': 'b' * 32})
    elif fault == 'count':
        lines[-1] = f'APEXEND:{TOKEN}:999999:{"0" * 64}\n'.encode()
    elif fault == 'trailer':
        lines.append(lines[-1])
    else:
        lines.append(lines[0])
    with pytest.raises(Blocked):
        installerlogs.decode(lines, TOKEN)


def test_serial_transport_has_size_limit(monkeypatch):
    monkeypatch.setattr(installerlogs, 'MAX_BYTES', 10)
    with pytest.raises(Blocked, match='limit'):
        installerlogs.decode(frames(), TOKEN)


def test_serial_transport_rejects_reordered_chunks():
    lines = frames({'schema': 1, 'token': TOKEN, 'padding': 'x' * 1000})
    lines[0], lines[1] = lines[1], lines[0]
    with pytest.raises(Blocked):
        installerlogs.decode(lines, TOKEN)


@pytest.mark.parametrize('info', [None, {'role': 'builder'}, {'role': 'test', 'iso': None}])
def test_capture_prepare_refuses_other_environments(tmp_path, monkeypatch, info):
    monkeypatch.setattr(installerlogs, 'alive', lambda _: info)
    with pytest.raises(Blocked):
        installerlogs.prepare(tmp_path)


@pytest.fixture
def capture(tmp_path, monkeypatch):
    run = tmp_path / 'vm-runs/fixture'
    run.mkdir(parents=True)
    iso = tmp_path / 'fixture.iso'
    iso.write_bytes(b'ISO fixture')
    info = {'role': 'test', 'iso': str(iso), 'artifacts_dir': str(run)}
    (run / 'vm.json').write_text(json.dumps(info))
    monkeypatch.setattr(installerlogs, 'alive', lambda _: info)
    request = installerlogs.prepare(tmp_path)
    assert not (run / 'test-serial.log').exists()
    return tmp_path, run, request['token']


@pytest.mark.parametrize('fault', [None, 'missing', 'truncated', 'checksum'])
def test_collect_keeps_private_evidence_without_passing_acceptance(capture, fault):
    state, run, token = capture
    data = b'installer fixture log\n'
    item = {'data': base64.b64encode(data).decode(), 'sha256': hashlib.sha256(data).hexdigest(), 'truncated': False}
    logs = {name: dict(item) for name in ('anaconda.log', 'storage.log', 'program.log')}
    if fault == 'missing':
        logs.pop('storage.log')
    elif fault == 'truncated':
        logs['storage.log']['truncated'] = True
    elif fault == 'checksum':
        logs['storage.log']['sha256'] = '0' * 64
    lines = frames({'schema': 1, 'token': token, 'logs': logs})
    (run / 'test-serial.log').write_bytes(b''.join(lines).replace(TOKEN.encode(), token.encode()))
    result = installerlogs.collect(state, run, token)
    assert result['required_logs_complete'] == (fault is None)
    assert result['acceptance'] == 'NOT TESTED'
    assert Path(result['bundle']).stat().st_mode & 0o777 == 0o600
    with pytest.raises(Blocked, match='already exists'):
        installerlogs.collect(state, run, token)


def test_collect_rejects_path_traversal(capture):
    state, run, _ = capture
    with pytest.raises(Blocked):
        installerlogs.collect(state, run, '../../outside')


@pytest.mark.parametrize('arguments', [[], ['--serial']])
def test_collector_refuses_host_without_installer_marker(arguments):
    result = subprocess.run([sys.executable, ROOT / 'guest/installer-diagnostics.py', TOKEN, *arguments], capture_output=True, text=True)
    assert result.returncode != 0
    assert 'installer VM rescue login' in result.stderr
    assert not result.stdout


def test_guest_reader_bounds_logs_and_refuses_symlinks_or_devices(tmp_path):
    spec = importlib.util.spec_from_file_location('installer_diagnostics', ROOT / 'guest/installer-diagnostics.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.LIMIT = 10
    path = tmp_path / 'sample'
    path.write_bytes(b'123456789012')
    item = module.read_log(path)
    assert item['truncated'] and base64.b64decode(item['data']) == b'1234567890'
    link = tmp_path / 'link'
    link.symlink_to(path)
    assert 'error' in module.read_log(link)
    fifo = tmp_path / 'fifo'
    os.mkfifo(fifo)
    assert 'error' in module.read_log(fifo)
    assert 'error' in module.read_log(tmp_path / 'absent')


def test_guest_emitter_matches_receiver_with_mocked_installer(tmp_path, monkeypatch, capsys):
    spec = importlib.util.spec_from_file_location('installer_diagnostics', ROOT / 'guest/installer-diagnostics.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    marker = tmp_path / 'marker.json'
    marker.write_text(json.dumps({'reference': 'localhost/apex-payload:' + 'b' * 64}))
    boot = tmp_path / 'boot-id'
    boot.write_text('fixture-boot')
    monkeypatch.setattr(module, 'Path', lambda value: marker if value.endswith('installer-payload.json') else boot)
    monkeypatch.setattr(module.os, 'geteuid', lambda: 0)
    monkeypatch.setattr(module, 'read_log', lambda _: {'error': 'fixture has no logs'})
    def command(args, **kwargs):
        if args[0] == 'systemd-detect-virt':
            return subprocess.CompletedProcess(args, 0, 'kvm\n', '')
        return subprocess.CompletedProcess(args, 0, b'fixture observation\n', b'')
    monkeypatch.setattr(module.subprocess, 'run', command)
    module.main(TOKEN)
    received = installerlogs.decode(capsys.readouterr().out.encode().splitlines(keepends=True), TOKEN)
    assert received['boot_id'] == 'fixture-boot'
    assert received['payload']['reference'] == 'localhost/apex-payload:' + 'b' * 64
    assert received['logs']['anaconda.log']['error'] == 'fixture has no logs'
