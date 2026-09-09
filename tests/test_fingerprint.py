import importlib.util
import json
import subprocess
import sys
from types import SimpleNamespace

import pytest
from apexlib.common import ROOT
from apexlib.common import Blocked
from apexlib import pipeline

spec = importlib.util.spec_from_file_location('fingerprint_test', ROOT / 'guest/test-fingerprint.py')
fingerprint = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fingerprint)


def test_fake_device_runner_refuses_host():
    result = subprocess.run([sys.executable, ROOT / 'guest/test-fingerprint.py'], capture_output=True, text=True)
    assert result.returncode != 0
    assert 'isolated Fedora builder VM' in result.stderr


def test_source_checksum_checked_before_import(tmp_path):
    lock = json.loads((ROOT / 'config/fingerprint-tests.lock.json').read_text())
    with pytest.raises(ValueError, match='checksum'):
        fingerprint.verify_sources(tmp_path, lock)
    lock['files']['unreviewed.py'] = '0' * 64
    with pytest.raises(ValueError, match='inventory'):
        fingerprint.verify_sources(tmp_path, lock)


def test_fake_runner_rejects_unbound_build(tmp_path):
    with pytest.raises(Blocked, match='build ID'):
        pipeline.fingerprint_tests(tmp_path, '../mutable-tag')


@pytest.mark.parametrize('field', ['skipped', 'expectedFailures', 'testsRun'])
def test_skipped_or_missing_fake_cases_cannot_pass(field):
    result = SimpleNamespace(errors=[], failures=[], unexpectedSuccesses=[],
                             skipped=[], expectedFailures=[], testsRun=8)
    assert fingerprint.outcome(result) == 'PASS'
    setattr(result, field, 0 if field == 'testsRun' else ['missing case'])
    assert fingerprint.outcome(result) == 'BLOCKED'
