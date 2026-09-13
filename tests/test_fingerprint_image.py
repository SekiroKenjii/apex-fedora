import importlib.util
import subprocess
import sys

import pytest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

spec = importlib.util.spec_from_file_location('fingerprint_image', ROOT / 'guest/fingerprint-image.py')
image = importlib.util.module_from_spec(spec)
spec.loader.exec_module(image)


def inventories():
    before = ['kernel|0:7.1.13-200.fc44.x86_64', 'pipewire|0:1.6.8-1.fc44.x86_64']
    before += [name + '|0:50.4-1.fc44.x86_64' for name in sorted(image.ALLOWED_PACKAGES)]
    after = [line.replace('-1.fc44.', '-1.fc44.apex1.') if line.split('|')[0] in image.ALLOWED_PACKAGES else line
             for line in before]
    return '\n'.join(before), '\n'.join(after)


def test_only_three_package_releases_change():
    assert set(image.package_delta(*inventories())) == image.ALLOWED_PACKAGES


@pytest.mark.parametrize('mutation', ['kernel', 'pipewire', 'version', 'extra', 'missing', 'duplicate', 'unchanged'])
def test_refuses_unplanned_rpm_changes(mutation):
    before, after = inventories()
    if mutation == 'kernel':
        after = after.replace('7.1.13', '7.1.14')
    elif mutation == 'pipewire':
        after = after.replace('1.6.8', '1.6.9')
    elif mutation == 'version':
        after = after.replace('50.4', '50.5')
    elif mutation == 'extra':
        after += '\nnew|0:1.0-1.fc44.x86_64'
    elif mutation == 'missing':
        after = '\n'.join(after.splitlines()[1:])
    elif mutation == 'duplicate':
        after += '\n' + after.splitlines()[0]
    elif mutation == 'unchanged':
        after = before
    with pytest.raises(ValueError):
        image.package_delta(before, after)


def test_image_script_refuses_host():
    result = subprocess.run([sys.executable, ROOT / 'guest/fingerprint-image.py'], capture_output=True, text=True)
    assert result.returncode != 0
    assert 'isolated builder VM' in result.stderr
