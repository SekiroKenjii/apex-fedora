import errno
import importlib.util
import stat
import subprocess
import sys
from types import SimpleNamespace

import pytest
from apexlib.common import ROOT

spec = importlib.util.spec_from_file_location('live_write_denial', ROOT / 'guest/live-write-denial.py')
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def fixtures():
    result = []
    for name, size, partition in [('vda', 4 * 2**21, None), ('vdb', 48 * 2**21, None),
                                  ('vda1', 100, 1), ('vda2', 100, 2), ('vda3', 100, 3)]:
        result.append({'name': name, 'sectors': size, 'partition': partition,
                       'serial': 'apex-other-1' if name == 'vda' else None,
                       'dev': str(len(result)), 'ro': '1', 'virtio': True,
                       'parent': 'vda' if partition else 'block', 'holders': []})
    return result


def test_expected_inventory_is_not_whole_protection_acceptance():
    assert probe.validate_inventory(fixtures(), set(), set()) is None


@pytest.mark.parametrize('field,value', [('name', 'nvme0n1'), ('sectors', 1),
    ('serial', 'unrelated'), ('ro', '0'), ('ro', ''), ('virtio', False), ('holders', ['dm-0'])])
def test_changed_inventory_refuses_before_opening_devices(field, value):
    devices = fixtures()
    devices[0][field] = value
    with pytest.raises(RuntimeError):
        probe.validate_inventory(devices, set(), set())


@pytest.mark.parametrize('change', ['mounted', 'swap', 'missing-partition', 'extra-disk', 'wrong-parent'])
def test_active_or_unexpected_fixtures_refused(change):
    devices = fixtures()
    mounted, swaps = set(), set()
    if change == 'mounted':
        mounted.add(devices[2]['dev'])
    elif change == 'swap':
        swaps.add('/dev/vda2')
    elif change == 'missing-partition':
        devices.pop()
    elif change == 'extra-disk':
        devices.append(dict(devices[0], name='vdc'))
    else:
        devices[2]['parent'] = 'vdb'
    with pytest.raises(RuntimeError):
        probe.validate_inventory(devices, mounted, swaps)


@pytest.mark.parametrize('outcome,expected', [(errno.EPERM, 'PASS'), (errno.EROFS, 'PASS'),
    (errno.EIO, 'BLOCKED'), (errno.ENOSPC, 'BLOCKED'), (None, 'FAIL')])
def test_only_protection_errors_pass_after_actual_same_byte_write(monkeypatch, outcome, expected):
    calls = []
    monkeypatch.setattr(probe.os, 'open', lambda *args: 19)
    monkeypatch.setattr(probe.os, 'fstat', lambda fd: SimpleNamespace(st_mode=stat.S_IFBLK, st_rdev=7))
    monkeypatch.setattr(probe.os, 'pread', lambda *args: b'a' * 512)
    monkeypatch.setattr(probe.os, 'close', lambda fd: calls.append(('close', fd)))

    def pwrite(fd, data, offset):
        calls.append(('pwrite', fd, data, offset))
        if outcome is not None:
            raise OSError(outcome, 'fixture error')
        return len(data)

    monkeypatch.setattr(probe.os, 'pwrite', pwrite)
    result = probe.attempt({'name': 'vda', 'rdev': 7})
    assert result['status'] == expected
    assert calls == [('pwrite', 19, b'a' * 512, 0), ('close', 19)]
    assert result['before_sha256'] == result['after_sha256']


@pytest.mark.parametrize('kind', ['identity', 'not-block', 'short-read'])
def test_opened_identity_and_sector_checked_before_write(monkeypatch, kind):
    closed = []
    monkeypatch.setattr(probe.os, 'open', lambda *args: 19)
    monkeypatch.setattr(probe.os, 'fstat', lambda fd: SimpleNamespace(
        st_mode=stat.S_IFREG if kind == 'not-block' else stat.S_IFBLK,
        st_rdev=8 if kind == 'identity' else 7))
    monkeypatch.setattr(probe.os, 'pread', lambda *args: b'a' * 511)
    monkeypatch.setattr(probe.os, 'pwrite', lambda *args: pytest.fail('unexpected write'))
    monkeypatch.setattr(probe.os, 'close', lambda fd: closed.append(fd))
    with pytest.raises(RuntimeError):
        probe.attempt({'name': 'vda', 'rdev': 7})
    assert closed == [19]


def test_script_refuses_host_before_inventory_or_writes():
    result = subprocess.run([sys.executable, ROOT / 'guest/live-write-denial.py'],
                            capture_output=True, text=True, timeout=5)
    assert result.returncode != 0
    assert 'never physical hardware' in result.stderr


def test_readback_change_fails_even_when_write_reported_permission_error(monkeypatch):
    reads = iter([b'a' * 512, b'b' * 512])
    monkeypatch.setattr(probe.os, 'open', lambda *args: 19)
    monkeypatch.setattr(probe.os, 'fstat', lambda fd: SimpleNamespace(st_mode=stat.S_IFBLK, st_rdev=7))
    monkeypatch.setattr(probe.os, 'pread', lambda *args: next(reads))
    monkeypatch.setattr(probe.os, 'close', lambda fd: None)

    def denied(*args):
        raise OSError(errno.EPERM, 'fixture error')

    monkeypatch.setattr(probe.os, 'pwrite', denied)
    result = probe.attempt({'name': 'vda', 'rdev': 7})
    assert result['status'] == 'FAIL'
    assert result['before_sha256'] != result['after_sha256']


def test_main_stops_after_first_failed_attempt(monkeypatch, capsys):
    import json
    calls = []
    monkeypatch.setattr(probe, 'require_live_vm', lambda: None)
    monkeypatch.setattr(probe, 'inventory', fixtures)

    def failed(device):
        calls.append(device['name'])
        return {'status': 'FAIL'}

    monkeypatch.setattr(probe, 'attempt', failed)
    with pytest.raises(RuntimeError, match='Write denial did not pass'):
        probe.main()
    report = json.loads(capsys.readouterr().out)
    assert calls == ['vda'] and report['status'] == 'FAIL'
    assert report['full_protection_acceptance'] == 'NOT TESTED'


def test_inventory_change_stops_before_next_attempt(monkeypatch):
    inventories = iter([fixtures(), fixtures()[:-1]])
    monkeypatch.setattr(probe, 'require_live_vm', lambda: None)
    monkeypatch.setattr(probe, 'inventory', lambda: next(inventories))
    monkeypatch.setattr(probe, 'attempt', lambda *args: pytest.fail('unexpected attempt'))
    with pytest.raises(RuntimeError, match='state changed'):
        probe.main()
