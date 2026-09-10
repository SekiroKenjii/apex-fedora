import importlib.util
import json

import pytest

from apexlib.common import ROOT

spec = importlib.util.spec_from_file_location('elan_diagnostics_test', ROOT / 'tools/test-elan-diagnostics.py')
diagnostics = importlib.util.module_from_spec(spec)
spec.loader.exec_module(diagnostics)


def test_refuses_root_before_reading_source(monkeypatch, tmp_path):
    monkeypatch.setattr(diagnostics.os, 'geteuid', lambda: 0)
    with pytest.raises(ValueError, match='without root'):
        diagnostics.run(tmp_path / 'absent')


def test_checksum_refusal_precedes_compilation(tmp_path, monkeypatch):
    source = tmp_path / 'elan.c'
    source.write_text('unreviewed')
    monkeypatch.setattr(diagnostics.subprocess, 'check_output', lambda *a, **k: pytest.fail('Unexpected compilation'))
    with pytest.raises(ValueError, match='checksum'):
        diagnostics.run(source)


def test_diagnostic_is_opt_in_bounded_and_not_in_image():
    lock = json.loads((ROOT / 'config/elan-diagnostics.lock.json').read_text())
    patch = (ROOT / lock['patch']).read_text()
    assert 'disabled by default' in lock['status']
    assert 'self->apex_diag_events >= 16' in patch
    assert 'g_getenv ("APEX_ELAN_STATUS_DIAGNOSTICS"), "1"' in patch
    assert '== 0x04f3' in patch and '== 0x0c6e' in patch
    assert 'libfprint-elan-status-diagnostics' not in (ROOT / 'guest/build-rpms.sh').read_text()
    added = '\n'.join(line[1:] for line in patch.splitlines() if line.startswith('+') and not line.startswith('+++'))
    assert 'error->message' not in added
    assert added.count('transfer->buffer[0]') == 1
    for condition in ('!error && self->cmd == &pre_scan_cmd', 'transfer->endpoint == ELAN_EP_CMD_IN',
                      'transfer->length == 1 && transfer->actual_length == 1', 'transfer->buffer != NULL'):
        assert condition in added
    assert 'FP_DEBUG_TRANSFER' in added and 'G_MESSAGES_DEBUG' in added


@pytest.mark.parametrize('text', ['image-bytes', 'apex-elan-v1 arbitrary=PRIVATE',
                                 'apex-elan-v1 event=probe action=3 state=2 command=pre-scan expected=1 actual=1 status=0 domain=0 code=0 payload=secret'])
def test_test_output_contract_rejects_extra_payload(text):
    assert diagnostics.LINE.fullmatch(text) is None
