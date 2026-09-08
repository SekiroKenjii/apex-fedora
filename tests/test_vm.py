from pathlib import Path
import json
import subprocess
import pytest
from apexlib.common import Blocked, regular_file
from apexlib import vm


@pytest.fixture(autouse=True)
def fake_firmware(tmp_path, monkeypatch):
    original = vm.config()
    code = tmp_path / 'OVMF_CODE.fd'
    code.touch()
    original['builder']['firmware_code'] = str(code)
    monkeypatch.setattr(vm, 'config', lambda: original)


def test_device_path_rejected(tmp_path):
    with pytest.raises(Blocked):
        regular_file(Path("/dev/null"), within=tmp_path)


def test_symlink_disk_rejected(tmp_path):
    (tmp_path / "disk").write_bytes(b"qcow")
    (tmp_path / "link").symlink_to(tmp_path / "disk")
    with pytest.raises(Blocked):
        regular_file(tmp_path / "link", within=tmp_path)


def test_outside_disk_rejected(tmp_path):
    (tmp_path / "outside").write_bytes(b"qcow")
    inner = tmp_path / "state"
    inner.mkdir()
    with pytest.raises(Blocked):
        regular_file(tmp_path / "outside", within=inner)


def test_insufficient_memory_is_blocked(tmp_path, monkeypatch):
    monkeypatch.setattr(vm, "available_mib", lambda: 7000)
    with pytest.raises(Blocked, match="7680"):
        vm.resources(tmp_path, 6144, 1536, 1)


def test_qemu_uses_only_files_and_local_ports(tmp_path):
    for name in ("disk.qcow2", "builder-vars.fd", "seed.iso"):
        (tmp_path / name).touch()
    args = vm.command(tmp_path, tmp_path / "disk.qcow2", "builder", 6144, 4, tmp_path / "seed.iso", 22244)
    joined = " ".join(args)
    assert "hostfwd=tcp:127.0.0.1:22244-:22" in joined
    assert "-qmp" in args and "-monitor" in args
    for forbidden in ("vfio", "/dev/nvme", "usb-host", "virtfs", "docker.sock", "-soundhw"):
        assert forbidden not in joined


def test_qemu_option_injection_rejected(tmp_path):
    directory = tmp_path / "state,extra"
    directory.mkdir()
    for name in ("disk.qcow2", "builder-vars.fd"):
        (directory / name).touch()
    with pytest.raises(Blocked):
        vm.command(directory, directory / "disk.qcow2", "builder", 6144, 4)


def test_qemu_filename_injection_rejected(tmp_path):
    disk = tmp_path / 'test,file=/dev/null'
    disk.parent.mkdir(parents=True)
    disk.touch()
    (tmp_path / 'builder-vars.fd').touch()
    with pytest.raises(Blocked):
        vm.command(tmp_path, disk, 'builder', 6144, 4)


@pytest.mark.parametrize('state', [None, {'role': 'builder'}])
def test_power_loss_refuses_builder_or_absent_vm(tmp_path, monkeypatch, state):
    monkeypatch.setattr(vm, 'alive', lambda _: state)
    with pytest.raises(Blocked, match='disposable'):
        vm.power_loss(tmp_path)


def test_power_loss_uses_pid_handle_only_for_owned_test(tmp_path, monkeypatch):
    capture = tmp_path / 'vm-runs/fixture'
    capture.mkdir(parents=True)
    state = {'role': 'test', 'pid': 1234567, 'artifacts_dir': str(capture)}
    calls = []
    monkeypatch.setattr(vm, 'alive', lambda _: state)
    monkeypatch.setattr(vm.os, 'pidfd_open', lambda pid: calls.append(('open', pid)) or 123456)
    monkeypatch.setattr(vm.signal, 'pidfd_send_signal', lambda fd, sig: calls.append(('signal', fd, sig)))
    monkeypatch.setattr(vm.os, 'close', lambda fd: calls.append(('close', fd)))
    vm.power_loss(tmp_path)
    assert calls == [('open', 1234567), ('signal', 123456, vm.signal.SIGKILL), ('close', 123456)]
    assert (capture / 'power-loss.json').is_file()


def test_additional_disks_are_files_with_stable_serials(tmp_path):
    for name in ('disk.qcow2', 'other.qcow2', 'test-vars.fd'):
        (tmp_path / name).touch()
    args = vm.command(tmp_path, tmp_path / 'disk.qcow2', 'test', 4096, 4,
                      extra_disks=(tmp_path / 'other.qcow2',))
    assert f'if=none,id=apex-other-1,format=qcow2,file={tmp_path}/other.qcow2' in args
    assert 'virtio-blk-pci,drive=apex-other-1,serial=apex-other-1' in args
    assert '-nic' in args and 'none' in args


def test_additional_disk_injection_and_duplicate_are_rejected(tmp_path):
    for name in ('disk.qcow2', 'other,readonly=off.qcow2', 'test-vars.fd'):
        (tmp_path / name).touch()
    for extra in ('disk.qcow2', 'other,readonly=off.qcow2'):
        with pytest.raises(Blocked):
            vm.command(tmp_path, tmp_path / 'disk.qcow2', 'test', 4096, 4,
                       extra_disks=(tmp_path / extra,))


def test_builder_cannot_attach_additional_disk(tmp_path):
    for name in ('disk.qcow2', 'other.qcow2', 'builder-vars.fd'):
        (tmp_path / name).touch()
    with pytest.raises(Blocked, match='test VMs'):
        vm.command(tmp_path, tmp_path / 'disk.qcow2', 'builder', 6144, 4,
                   extra_disks=(tmp_path / 'other.qcow2',))


def test_resume_preserves_overlay_and_vars_but_removes_iso(tmp_path, monkeypatch):
    capture = tmp_path / 'vm-runs/example'
    capture.mkdir(parents=True)
    disk = capture / 'disk.qcow2'
    disk.touch()
    (capture / 'test-vars.fd').write_bytes(b'existing firmware state')
    (capture / 'test-serial.log').write_text('old boot log')
    saved = {'role': 'test', 'pid': 999, 'disk': str(disk), 'artifacts_dir': str(capture),
             'iso': '/must-not-be-opened.iso', 'guest_ssh': False,
             'command': ['must-not-be-executed']}
    (capture / 'vm.json').write_text(json.dumps(saved))
    monkeypatch.setattr(vm, 'alive', lambda _: None)
    monkeypatch.setattr(vm, 'resources', lambda *args: None)
    monkeypatch.setattr(vm, 'validate_disk', lambda *args: None)
    monkeypatch.setattr(vm.time, 'sleep', lambda _: None)
    calls = []
    class Process:
        pid = 123456
        def __init__(self, args, **kwargs):
            calls.append(args)
        def poll(self):
            return None
    monkeypatch.setattr(vm.subprocess, 'Popen', Process)
    vm.resume_test(tmp_path, capture, without_iso=True)
    assert 'must-not-be-executed' not in calls[0]
    assert not any('cdrom' in arg for arg in calls[0])
    assert f'if=virtio,format=qcow2,file={disk}' in calls[0]
    assert (capture / 'test-vars.fd').read_bytes() == b'existing firmware state'
    assert len(list(capture.glob('before-resume-*-serial.log'))) == 1
    assert json.loads((capture / 'vm.json').read_text())['iso'] is None


def test_compare_disks_checks_virtual_contents_and_rejects_running_vm(tmp_path, monkeypatch):
    capture = tmp_path / 'vm-runs/example'
    capture.mkdir(parents=True)
    base, overlay = tmp_path / 'base.qcow2', capture / 'disk.qcow2'
    subprocess.run(['qemu-img', 'create', '-f', 'qcow2', base, '8M'], check=True, capture_output=True)
    subprocess.run(['qemu-img', 'create', '-f', 'qcow2', '-F', 'qcow2', '-b', base, overlay], check=True, capture_output=True)
    saved = {'role': 'test', 'source_disk': str(base), 'disk': str(overlay), 'artifacts_dir': str(capture)}
    (capture / 'vm.json').write_text(json.dumps(saved))
    monkeypatch.setattr(vm, 'alive', lambda _: None)
    assert vm.compare_disks(tmp_path, capture)['disks'][0]['unchanged']
    subprocess.run(['qemu-io', '-f', 'qcow2', '-c', 'write -P 0x42 4096 512', overlay], check=True, capture_output=True)
    assert not vm.compare_disks(tmp_path, capture)['disks'][0]['unchanged']
    monkeypatch.setattr(vm, 'alive', lambda _: {'role': 'test'})
    with pytest.raises(Blocked, match='Stop the VM'):
        vm.compare_disks(tmp_path, capture)
