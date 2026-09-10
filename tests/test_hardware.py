import json
from types import SimpleNamespace

from apexlib import hardware


def test_file_read_is_bounded_and_absence_is_explicit(tmp_path):
    path = tmp_path / 'sample'
    path.write_bytes(b'a' * (hardware.LIMIT + 1))
    assert hardware.read(path)['truncated'] is True
    assert len(hardware.read(path)['text']) == hardware.LIMIT
    assert hardware.read(tmp_path / 'absent')['status'] == 'UNAVAILABLE'


def test_snapshot_never_claims_sensor_or_modifies_audio(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(hardware, 'read', lambda _: {'status': 'UNAVAILABLE'})
    monkeypatch.setattr(hardware, 'command', lambda args: calls.append(args) or {'status': 'UNAVAILABLE'})
    path = hardware.collect(tmp_path)
    report = json.loads(path.read_text())
    assert report['audio_acceptance'] == report['fingerprint_acceptance'] == 'NOT TESTED'
    assert report['cold_boot_provenance'] == report['prior_workaround_state'] == 'UNKNOWN'
    assert path.stat().st_mode & 0o077 == 0
    flattened = ' '.join(' '.join(args) for args in calls)
    for forbidden in ('hda-verb', 'Enroll', 'Claim', 'Release', 'sudo', 'restart', 'set-volume'):
        assert forbidden not in flattened
    bus = next(args for args in calls if args[0] == 'busctl')
    assert bus[3] == 'org.freedesktop.DBus'
    assert 'GetNameOwner' in bus


def test_failed_command_is_not_an_empty_success(monkeypatch):
    monkeypatch.setattr(hardware.shutil, 'which', lambda _: '/test/tool')
    monkeypatch.setattr(hardware.subprocess, 'run', lambda *a, **kw: SimpleNamespace(returncode=1, stdout='', stderr='permission denied'))
    assert hardware.command(['journalctl'])['status'] == 'UNAVAILABLE'
