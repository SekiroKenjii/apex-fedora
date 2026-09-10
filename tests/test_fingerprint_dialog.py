import importlib.util
import json
from pathlib import Path

import pytest

from apexlib.common import ROOT

spec = importlib.util.spec_from_file_location('dialog_test', ROOT / 'tools/test-fingerprint-dialog.py')
dialog = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dialog)


def test_checksum_refusal_precedes_patch_or_compile(tmp_path, monkeypatch):
    source = tmp_path / 'dialog.c'
    source.write_text('unreviewed code')
    monkeypatch.setattr(dialog.subprocess, 'run', lambda *a, **k: pytest.fail('Unexpected build'))
    with pytest.raises(ValueError, match='checksum'):
        dialog.run(source)


def test_handler_test_refuses_root_before_reading_source(monkeypatch, tmp_path):
    monkeypatch.setattr(dialog.os, 'geteuid', lambda: 0)
    with pytest.raises(ValueError, match='without root'):
        dialog.run(tmp_path / 'absent')


def test_extraction_retains_nested_condition_and_refuses_duplicates():
    text = '\nstatic void\nhandle_enroll_signal (int x)\n{ if (x) { x++; } }\n'
    assert dialog.function(text, 'handle_enroll_signal').endswith('{ x++; } }')
    with pytest.raises(ValueError, match='one pinned'):
        dialog.function(text + text, 'handle_enroll_signal')


def test_patch_only_preserves_cleanup_state_and_is_not_installed():
    lock = json.loads((ROOT / 'config/gnome-fingerprint.lock.json').read_text())
    patch = (ROOT / lock['patch']).read_text()
    removed = [line for line in patch.splitlines() if line.startswith('-') and not line.startswith('---')]
    assert len(removed) == 2
    assert 'DIALOG_STATE_DEVICE_CLAIMED' in removed[0]
    assert 'DIALOG_STATE_DEVICE_ENROLLING' in removed[1]
    added = [line for line in patch.splitlines() if line.startswith('+') and not line.startswith('+++')]
    assert 'if (self->dialog_state & DIALOG_STATE_DEVICE_ENROLL_STOPPING)' in patch
    assert all('/*' in line or line.lstrip('+ ').startswith(('*', 'if ', 'return;')) or line == '+' for line in added)
    assert 'experimental' in lock['status']
    assert 'gnome-fingerprint-retain-claim' not in (ROOT / 'guest/build-rpms.sh').read_text()


def test_both_distribution_sources_are_pinned():
    lock = json.loads((ROOT / 'config/gnome-fingerprint.lock.json').read_text())
    assert len(lock['reviewed_sources']) == 2
    assert lock['reviewed_sources'][0]['sha256'] == lock['source_sha256']
    assert lock['reviewed_sources'][1]['sha256'] != lock['source_sha256']
    assert all(len(item['package_sha256']) == 64 for item in lock['reviewed_sources'])
    assert 'not independently validated' in lock['source_trust']


def test_lifecycle_scope_keeps_real_cancel_and_fake_bus_explicit():
    assert {'enroll_stop', 'enroll_stop_cb', 'on_device_owner_changed'} <= set(dialog.HANDLERS)
    assert {'cancel-twice', 'close-pending', 'daemon-gone', 'stop-error'} <= set(dialog.CASES)
    template = (ROOT / 'tests/fixtures/fingerprint-dialog-harness.c').read_text()
    assert '#include <gio/gio.h>' in template
    assert '#define g_cancellable_cancel' not in template
    assert 'g_bus_get' not in template
