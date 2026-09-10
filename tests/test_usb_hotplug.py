import json
from pathlib import Path
import subprocess

import pytest
from apexlib import vm
from apexlib.common import Blocked


def test_usb_controller_is_emulated_and_test_only(tmp_path):
    for name in ('disk', 'test-vars.fd', 'builder-vars.fd'):
        (tmp_path / name).touch()
    args = vm.command(tmp_path, tmp_path / 'disk', 'test', 4096, 4, usb_test_bus=True)
    assert 'qemu-xhci,id=apex-usb' in args
    assert 'usb-host' not in ' '.join(args)
    with pytest.raises(Blocked, match='disposable'):
        vm.command(tmp_path, tmp_path / 'disk', 'builder', 6144, 4, usb_test_bus=True)


@pytest.mark.parametrize('info', [None, {'role': 'builder'}, {'role': 'test'},
    {'role': 'test', 'usb_test_bus': True, 'hotplug_usb': {'source': 'previous'}},
    {'role': 'test', 'usb_test_bus': True, 'extra_disks': ['one', 'two']}])
def test_invalid_hotplug_scope_fails_before_source_access(tmp_path, monkeypatch, info):
    monkeypatch.setattr(vm, 'alive', lambda _: info)
    with pytest.raises(Blocked):
        vm.hotplug_usb(tmp_path, Path('/dev/null'))


@pytest.mark.parametrize('fail', [False, True])
def test_hotplug_registers_comparison_even_when_qmp_fails(tmp_path, monkeypatch, fail):
    capture = tmp_path / 'vm-runs/fixture'
    capture.mkdir(parents=True)
    source = tmp_path / 'source.qcow2'
    subprocess.run(['qemu-img', 'create', '-f', 'qcow2', source, '4M'], check=True, capture_output=True)
    saved = {'role': 'test', 'usb_test_bus': True, 'artifacts_dir': str(capture)}
    (tmp_path / 'vm.json').write_text(json.dumps(saved))
    monkeypatch.setattr(vm, 'alive', lambda _: json.loads((tmp_path / 'vm.json').read_text()))
    calls = []

    class Connection:
        def __init__(self, path):
            pass
        def call(self, name, arguments):
            calls.append((name, arguments))
            if fail and name == 'device_add':
                raise Blocked('simulated QMP failure')
            return {}
        def close(self):
            pass

    monkeypatch.setattr(vm, 'QMP', Connection)
    if fail:
        with pytest.raises(Blocked, match='simulated'):
            vm.hotplug_usb(tmp_path, source)
    else:
        assert vm.hotplug_usb(tmp_path, source)['status'] == 'ATTACHED'
    info = json.loads((capture / 'vm.json').read_text())
    assert info['extra_disks'] == [str(capture / 'hotplug-usb.qcow2')]
    assert info['source_extra_disks'] == [str(source)]
    report = json.loads((capture / 'hotplug-request.json').read_text())
    assert report['status'] == ('INCOMPLETE' if fail else 'ATTACHED')
    assert report['guest_protection'] == 'NOT TESTED'
    assert calls[0][1]['read-only'] is False
    assert calls[1][1]['serial'] == 'apex-usb-fixture'
