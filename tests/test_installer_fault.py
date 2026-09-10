import importlib.util
import json
import hashlib
from pathlib import Path

import pytest

from apexlib import installerfault
from apexlib.common import Blocked, ROOT


def load_guest():
    spec = importlib.util.spec_from_file_location('fault_guest', ROOT / 'guest/test-installer-fault.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def report(**changes):
    value = {'case': 'missing-signature', 'status': 'PASS', 'returncode': 1,
             'preflight': {'status': 'FAIL'}, 'upstream_log_created': False,
             'selinux_after': 'Enforcing'}
    return value | changes


def wire(value):
    return ('APEXFAULT:' + json.dumps(value) + '\r\n').encode()


def test_named_cases_match_guest():
    assert set(installerfault.CASES) == set(load_guest().CASES)


@pytest.mark.parametrize('change', [{'status': 'FAIL'}, {'returncode': 0},
                                  {'preflight': {'status': 'PASS'}},
                                  {'upstream_log_created': True}, {'selinux_after': 'Permissive'},
                                  {'case': 'wrong-key'}])
def test_report_requires_actual_rejection(change):
    with pytest.raises(Blocked):
        installerfault.parse(wire(report(**change)), 'missing-signature')


def test_report_requires_single_complete_frame():
    value = wire(report())
    assert installerfault.parse(value, 'missing-signature')['status'] == 'PASS'
    for broken in (value[:-2], value+value, b'no report\n'):
        with pytest.raises(Blocked):
            installerfault.parse(broken, 'missing-signature')


def test_host_refuses_mutation_outside_offline_installer(tmp_path, monkeypatch):
    monkeypatch.setattr(installerfault.vm, 'alive', lambda _: {'role': 'builder'})
    with pytest.raises(Blocked, match='offline'):
        installerfault.execute(tmp_path, 'missing-signature')
    with pytest.raises(Blocked, match='known case'):
        installerfault.execute(tmp_path, 'wrong-key')
    with pytest.raises(Blocked, match='known case'):
        installerfault.execute(tmp_path, 'missing-signature', Path('private.key'))


def test_guest_refuses_host_before_touching_payload(monkeypatch):
    guest = load_guest()
    monkeypatch.setattr(guest.os, 'geteuid', lambda: 0)
    monkeypatch.setattr(guest, 'run', lambda _: 'none')
    with pytest.raises(RuntimeError, match='QEMU'):
        guest.guard('missing-signature')


def test_guest_refuses_reused_boot(tmp_path, monkeypatch):
    guest = load_guest()
    previous = tmp_path / 'preflight.json'
    previous.write_text('{}')
    monkeypatch.setattr(guest, 'PREFLIGHT', previous)
    with pytest.raises(RuntimeError, match='already entered'):
        guest.unchanged_start_state()


def test_collector_refuses_running_vm(tmp_path, monkeypatch):
    monkeypatch.setattr(installerfault.vm, 'alive', lambda _: {'role': 'test'})
    with pytest.raises(Blocked, match='Power off'):
        installerfault.collect(tmp_path, tmp_path / 'run')


@pytest.mark.parametrize('case', installerfault.CASES)
def test_mutation_preserves_backup_and_touches_only_fixture(tmp_path, monkeypatch, case):
    guest = load_guest()
    payload, trust = tmp_path / 'payload', tmp_path / 'trust'
    payload.mkdir(); trust.mkdir()
    blob = b'{"test-config":true}'
    digest = hashlib.sha256(blob).hexdigest()
    (payload / digest).write_bytes(blob)
    (payload / 'manifest.json').write_text(json.dumps({'config': {'digest': 'sha256:' + digest}}))
    (payload / 'signature-1').write_bytes(b'synthetic signature')
    (trust / 'payload.pub').write_text('original public fixture')
    metadata = {'digest': 'sha256:' + 'a'*64, 'image_id': 'sha256:' + digest,
                'purpose': 'development-installer-only', 'reference': 'localhost/apex-payload@sha256:' + 'a'*64,
                'identity': 'localhost/apex-payload:' + 'a'*64}
    (trust / 'payload.json').write_text(json.dumps(metadata))
    for name, value in {'PAYLOAD': payload, 'TRUST': trust, 'FAULT_DIRECTORY': tmp_path / 'fault',
                        'POLICY': tmp_path / 'policy.json',
                        'PREFLIGHT_PROGRAM': ROOT / 'guest/installer-preflight.py'}.items():
        monkeypatch.setattr(guest, name, value)
    # Parsing/cryptography of the alternate key is covered in the real VM case.
    result = guest.mutate(case, '-----BEGIN PUBLIC KEY-----\nsynthetic fixture\n')
    original = (tmp_path / 'fault/original').read_bytes()
    assert hashlib.sha256(original).hexdigest() == result['before_sha256']
    assert result['before_sha256'] != result['after_sha256']
    if case == 'corrupt-blob':
        assert (payload / digest).stat().st_size == len(blob)
    if case == 'wrong-key':
        assert json.loads((tmp_path / 'policy.json').read_text())['default'] == [{'type': 'reject'}]
    with pytest.raises(FileExistsError):
        guest.mutate(case, '')
