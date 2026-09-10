import importlib.util

import pytest
from apexlib.common import ROOT

spec = importlib.util.spec_from_file_location('grub_fragment', ROOT / 'guest/fix-grub-fragment.py')
fragment = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fragment)


def test_final_command_is_not_concatenated_with_bootupd_comment():
    data = b'# greenboot\nset boot_success=0\nsave_env boot_success'
    after = fragment.repair(data)
    assert after == data + b'\n'
    assembled = after + b'### END 08_greenboot.cfg ###\n'
    assert assembled.splitlines()[-2] == b'save_env boot_success'
    assert fragment.repair(after) == after


@pytest.mark.parametrize('data', [b'', b'save_env something_else', b'save_env boot_success### END'])
def test_unknown_fragment_is_not_silently_rewritten(data):
    with pytest.raises(ValueError, match='unknown final command'):
        fragment.repair(data)
