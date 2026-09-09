import importlib.util

import pytest

from apexlib.common import ROOT

spec = importlib.util.spec_from_file_location('live_probe', ROOT / 'guest/live-probe.py')
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


@pytest.mark.parametrize('uid,virtual,cmdline', [
    (1000, {'returncode': 0, 'stdout': 'kvm'}, 'root=live:CDLABEL=Apex-Live'),
    (0, {'returncode': 1, 'stdout': 'kvm'}, 'root=live:CDLABEL=Apex-Live'),
    (0, {'returncode': 0, 'stdout': 'none'}, 'root=live:CDLABEL=Apex-Live'),
    (0, {'returncode': 0, 'stdout': 'kvm'}, 'root=UUID=test'),
    (0, {'returncode': 0, 'stdout': 'kvm'}, 'root=live:CDLABEL=Apex-Live-other'),
])
def test_refuses_non_root_non_live_and_physical_sessions(uid, virtual, cmdline):
    with pytest.raises(RuntimeError):
        probe.require_live_vm(uid, virtual, cmdline)


def test_live_vm_scope_check_does_not_declare_acceptance():
    assert probe.require_live_vm(0, {'returncode': 0, 'stdout': 'kvm\n'},
                                 'quiet root=live:CDLABEL=Apex-Live') is None


def test_missing_attributes_are_errors_not_inferred_values(tmp_path):
    (tmp_path / 'vda').mkdir()
    (tmp_path / 'vda/ro').write_text('1\n')
    report = probe.block_observations(tmp_path)['vda']
    assert report['attributes']['ro']['text'] == '1\n'
    assert 'error' in report['attributes']['size']


def test_truncated_file_is_not_given_a_complete_hash(tmp_path):
    path = tmp_path / 'large'
    path.write_bytes(b'a' * 262145)
    report = probe.text_file(path)
    assert report['truncated'] and report['sha256'] is None
    assert len(report['text']) == 262144


def test_missing_label_is_reported_as_error(tmp_path, monkeypatch):
    path = tmp_path / 'helper'
    path.write_text('fixture')

    def unavailable(*args, **kwargs):
        raise OSError('No security label')

    monkeypatch.setattr(probe.os, 'getxattr', unavailable)
    assert probe.file_metadata(path) == {'error': 'No security label'}


def test_probe_collects_flatpak_label_and_live_bootloader_mask():
    source = (ROOT / 'guest/live-probe.py').read_text()
    assert "'bootloader-update.service'" in source
    assert "'flatpak-system-helper.service'" in source
    assert '/run/rootfsbase/usr/libexec/flatpak-system-helper' in source
