"""Evaluate a retained real-VM recovery collection against the two-boot limit."""
import json
import os
from pathlib import Path

import pytest

from apexlib.common import atomic_json
from apexlib.recovery import evaluate_gdm


@pytest.mark.integration
def test_gdm_automatic_fallback_after_two_failures():
    report = os.environ.get('APEX_RECOVERY_REPORT')
    fixture = os.environ.get('APEX_RECOVERY_FIXTURE')
    if not report or not fixture:
        pytest.skip('NOT TESTED: supply a real recovery collection and its signed fixture')
    report = Path(report)
    data = json.loads(report.read_text())
    images = json.loads(Path(fixture).read_text())['images']
    records = [c for c in data['commands'] if c['command'] == 'journalctl -u gdm -u greenboot-healthcheck -u greenboot-set-rollback-trigger --no-pager -o json']
    assert len(records) == 1 and records[0]['returncode'] == 0
    result = evaluate_gdm(records[0]['stdout'], images['a']['digest'], images['b']['digest'])
    atomic_json(report.parent / 'gdm-evaluation.json', result)
    assert result['two_failure_limit'] == 'PASS', result
