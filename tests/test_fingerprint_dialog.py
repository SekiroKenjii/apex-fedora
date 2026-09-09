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
    assert all('/*' in line or line.lstrip('+ ').startswith('*') for line in added)
    assert 'experimental' in lock['status']
    assert 'gnome-fingerprint-retain-claim' not in (ROOT / 'guest/build-rpms.sh').read_text()
