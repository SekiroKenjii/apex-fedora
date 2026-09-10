import importlib.util
import sys
from pathlib import Path

import pytest
from apexlib.common import ROOT


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'guest' / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sys.modules['apex_live_write'] = load('apex_live_write', 'live-write-denial.py')
usb = load('usb_probe', 'live-usb-probe.py')
lock = load('lock_probe', 'live-lock-fault.py')


def test_usb_ancestor_requires_usb_descriptor_and_expected_serial(tmp_path):
    parent = tmp_path / 'usb2/2-1'
    parent.mkdir(parents=True)
    (parent / 'serial').write_text('apex-usb-fixture')
    leaf = parent / 'host2/block/sda'
    assert usb.fixture_parent(leaf) is None
    for field in ('idVendor', 'idProduct'):
        (parent / field).write_text('fixture')
    assert usb.fixture_parent(leaf) == str(parent)
    (parent / 'serial').write_text('unrelated-usb')
    assert usb.fixture_parent(leaf) is None


def test_non_usb_serial_is_never_read(tmp_path, monkeypatch):
    (tmp_path / 'serial').touch()
    monkeypatch.setattr(Path, 'read_text', lambda *args, **kwargs: pytest.fail('read unrelated serial'))
    assert usb.fixture_parent(tmp_path / 'device/block/vda') is None


def test_expected_kernel_denial_is_accepted():
    lock.validate_denial(1, 'blockdev: ioctl error on BLKROSET: Permission denied',
                         {'CapEff': '1ffffdfffff', 'CapBnd': '1ffffdfffff'}, '0', True)


@pytest.mark.parametrize('field,value', [('code', 0), ('error', 'I/O error'),
    ('caps', {}), ('caps', {'CapEff': '1ffffffffff', 'CapBnd': '1ffffdfffff'}),
    ('readonly', '1'), ('latched', False)])
def test_other_failures_do_not_pass_lock_test(field, value):
    arguments = dict(code=1, error='Permission denied',
                     caps={'CapEff': '1ffffdfffff', 'CapBnd': '1ffffdfffff'}, readonly='0', latched=True)
    arguments[field] = value
    with pytest.raises(RuntimeError):
        lock.validate_denial(**arguments)


def test_lock_fault_refuses_host_before_inventory_or_capability_change():
    with pytest.raises(RuntimeError):
        lock.require_initramfs()
