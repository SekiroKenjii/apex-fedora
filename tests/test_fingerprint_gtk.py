import copy
import importlib.util
import subprocess
import sys

import pytest
from apexlib.common import ROOT

spec = importlib.util.spec_from_file_location('gtk_test_runner', ROOT / 'guest/fingerprint-gtk.py')
gtk = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gtk)


def results():
    return {variant: {name: {'status': 'PASS' if variant == 'patched' else 'FAIL',
                             'ready': True, 'assertion_failure': variant == 'original',
                             'returncode': 0 if variant == 'patched' else 134}
                      for name in gtk.CASES} for variant in ('original', 'patched')}


def test_requires_full_dialog_regression():
    assert gtk.summary_status(results()) == 'PASS'


@pytest.mark.parametrize('mutation', ['missing-variant', 'missing-case', 'startup-failure',
                                    'wrong-baseline-error', 'patched-error', 'false-success'])
def test_rejects_incomplete_or_false_success(mutation):
    report = copy.deepcopy(results())
    if mutation == 'missing-variant':
        del report['original']
    elif mutation == 'missing-case':
        del report['patched']['daemon-replace']
    elif mutation == 'startup-failure':
        report['original']['error-close']['ready'] = False
    elif mutation == 'wrong-baseline-error':
        report['original']['cancel-twice']['assertion_failure'] = False
    elif mutation == 'patched-error':
        report['patched']['close-pending']['status'] = 'FAIL'
    elif mutation == 'false-success':
        report['patched']['error-close']['returncode'] = 1
    assert gtk.summary_status(report) == 'FAIL'


def test_runner_refuses_working_host():
    result = subprocess.run([sys.executable, ROOT / 'guest/fingerprint-gtk.py'], capture_output=True, text=True)
    assert result.returncode != 0
    assert 'isolated builder VM' in result.stderr


def test_dialog_uses_complete_sources_and_real_widget_signals():
    harness = (ROOT / 'guest/fingerprint-gtk.c').read_text()
    assert '#include "cc-fingerprint-dialog.c"' in harness
    assert 'g_signal_emit_by_name (dialog->cancel_button, "clicked")' in harness
    assert 'adw_dialog_close (ADW_DIALOG (dialog))' in harness
    runner = (ROOT / 'guest/fingerprint-gtk.py').read_text()
    assert "users / 'cc-fingerprint-manager.c'" in runner
    assert "'-fsanitize=address,undefined'" in runner
    assert "source_tar.extractall(extracted, filter='data')" in runner
