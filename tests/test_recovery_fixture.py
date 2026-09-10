import importlib.util
from pathlib import Path

import pytest


def module():
    spec = importlib.util.spec_from_file_location('recovery_fixture', Path(__file__).resolve().parents[1] / 'guest/recovery-fixture.py')
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def test_grub_repair_changes_only_the_reviewed_separator():
    m = module()
    before = b'prefix\n' + m.BROKEN + b'\nsuffix\n'
    after = m.repaired_config(before, b'save_env boot_success\n')
    assert after == b'prefix\n' + m.FIXED + b'\nsuffix\n'
    assert len(after) == len(before) + 1


@pytest.mark.parametrize('value', [b'', b'save_env boot_success', b'unknown\n'])
def test_repair_requires_the_fixed_image_fragment(value):
    m = module()
    with pytest.raises(ValueError):
        m.repaired_config(m.BROKEN, value)


def test_repair_refuses_unknown_repeated_and_already_repaired_configs():
    m = module()
    for value in (b'unknown', m.BROKEN * 2, m.FIXED, m.BROKEN + m.FIXED):
        with pytest.raises(ValueError):
            m.repaired_config(value, b'save_env boot_success\n')


def test_fault_is_scoped_to_one_digest_and_preserves_real_service_failure():
    m = module()
    source = m.fault_payload('sha256:' + 'b' * 64, Path('/var/lib/apex-recovery-test/fixture'))
    compile(source, 'fault', 'exec')
    assert "phase == 'gdm-start' and current == 'sha256:" + 'b' * 64 in source
    assert "sys.exit(42)" in source
    assert 'boot_counter=' not in source
    with pytest.raises(ValueError):
        m.fault_payload('bad; command', Path('/var/tmp'))


@pytest.mark.parametrize('value', ['', 'sha256:' + 'a' * 64 + '; command', 'sha256:' + 'b' * 64])
def test_runner_refuses_invalid_or_identical_fixture_digests(value):
    from apexlib.common import Blocked
    spec = importlib.util.spec_from_file_location('recovery_vm', Path(__file__).resolve().parents[1] / 'tools/recovery-vm.py')
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    fixture = {'status': 'PASS', 'id': 'a' * 32,
               'images': {'a': {'digest': value}, 'b': {'digest': 'sha256:' + 'b' * 64}}}
    with pytest.raises(Blocked):
        runner.validate_fixture(fixture)


def test_preset_pins_the_tested_retry_semantics():
    root = Path(__file__).resolve().parents[1]
    config = (root / 'system_files/usr/share/apex/greenboot.conf').read_text()
    assert 'GREENBOOT_MAX_BOOT_ATTEMPTS=1\n' in config
    assert 'greenboot-0.16.4-0.fc44' in (root / 'guest/image-configure.sh').read_text()
