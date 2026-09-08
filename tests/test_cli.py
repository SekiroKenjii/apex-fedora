import json
import os
import subprocess
import sys

import pytest
from apexlib.common import ROOT


@pytest.mark.parametrize('outside', [False, True])
def test_cli_runs_as_documented_without_pythonpath(tmp_path, outside):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
    env.pop('PYTHONPATH', None)
    cwd = tmp_path if outside else ROOT
    script = str(ROOT / 'tools/apex.py') if outside else 'tools/apex.py'
    result = subprocess.run([sys.executable, script, 'decode-coefficient', '0x20', '0x477', '0x74'],
                            cwd=cwd, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)
    help_result = subprocess.run([sys.executable, script, '--help'], cwd=cwd, env=env,
                                 capture_output=True, text=True)
    assert help_result.returncode == 0 and 'installer-logs' in help_result.stdout
