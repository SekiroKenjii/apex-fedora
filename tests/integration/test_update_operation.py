"""Opt in to one operation on the already running, isolated A/B guest."""
import os
from pathlib import Path
import subprocess
import sys

import pytest

from apexlib.common import ROOT, state_dir, regular_file

pytestmark = pytest.mark.integration


def test_update_operation():
    values = [os.environ.get(name) for name in ('APEX_UPDATE_ACTION', 'APEX_UPDATE_FIXTURE', 'APEX_UPDATE_ACCESS')]
    if not all(values):
        pytest.skip('NOT TESTED: supply an A/B action, signed fixture and private test access')
    action, fixture, access = values
    runtime = state_dir()
    regular_file(Path(fixture) / 'output/results.json', within=runtime)
    regular_file(Path(access) / 'credentials.json', within=runtime)
    # The runner validates the current QEMU PID, endpoint, parent and consumer policy.
    # It does not start a VM, reboot it or shut it down on test failure.
    subprocess.run([sys.executable, ROOT / 'tools/update-vm.py', action, fixture, access], check=True)
