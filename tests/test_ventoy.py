import importlib.util
import json
from pathlib import Path
import subprocess

import pytest
from apexlib import vm
from apexlib.common import Blocked, ROOT
from apexlib.ventoy import verify_ubuntu


def test_usb_boot_command_is_emulated_and_has_no_cdrom(tmp_path):
    for name in ('target', 'other', 'usb', 'test-vars.fd'):
        (tmp_path / name).touch()
    args = vm.command(tmp_path, tmp_path / 'target', 'test', 4096, 4,
                      extra_disks=(tmp_path / 'other', tmp_path / 'usb'), boot_usb=True)
    assert 'qemu-xhci,id=apex-usb' in args
    assert 'usb-storage,bus=apex-usb.0,drive=apex-boot-usb,serial=apex-ventoy-fixture,bootindex=1' in args
    assert 'virtio-blk-pci,drive=apex-other-1,serial=apex-other-1' in args
    assert not any('cdrom' in arg or 'usb-host' in arg or 'readonly=on,file=' + str(tmp_path) in arg for arg in args)
    assert '-nic' in args and 'none' in args


@pytest.mark.parametrize('options', [{'iso': Path('/missing.iso')}, {'usb_test_bus': True},
    {'guest_ssh': True}, {'disk': None}, {'extra_disks': ()}])
def test_conflicting_usb_boot_refused_before_disk_access(tmp_path, monkeypatch, options):
    monkeypatch.setattr(vm, 'alive', lambda _: None)
    args = dict(disk=Path('/missing'), extra_disks=(Path('/other'),), boot_usb=Path('/dev/null'))
    args.update(options)
    with pytest.raises(Blocked, match='USB boot'):
        vm.start(tmp_path, **args)


def test_usb_resume_refuses_topology_change(tmp_path, monkeypatch):
    capture = tmp_path / 'vm-runs/example'
    capture.mkdir(parents=True)
    (capture / 'vm.json').write_text(json.dumps({'role': 'test', 'artifacts_dir': str(capture), 'boot_usb': True}))
    monkeypatch.setattr(vm, 'alive', lambda _: None)
    with pytest.raises(Blocked, match='fresh USB test'):
        vm.resume_test(tmp_path, capture)


def fixture_module():
    spec = importlib.util.spec_from_file_location('ventoy_fixture', ROOT / 'guest/ventoy-fixture.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_media_builder_rejects_host_before_commands(monkeypatch):
    module = fixture_module()
    monkeypatch.setattr(module.os, 'geteuid', lambda: 1000)
    monkeypatch.setattr(module, 'run', lambda *args, **kwargs: pytest.fail('Host command ran'))
    with pytest.raises(RuntimeError, match='isolated builder'):
        module.main()


def test_arbitrary_loop_operand_refused():
    with pytest.raises(RuntimeError, match='newly allocated loop'):
        fixture_module().verify_loop('/dev/vda', Path('/var/tmp/new.raw'))


@pytest.mark.parametrize('case', ['unexpected-name', 'checksum', 'symlink', 'version'])
def test_fixture_rejects_unverified_inputs(tmp_path, case):
    module = fixture_module()
    names = ('ventoy.tar.gz', 'Apex-Live.iso', 'Ubuntu.iso')
    for name in names:
        (tmp_path / name).write_bytes(b'input')
    request = {'files': {name: module.digest(tmp_path / name) for name in names}, 'ventoy_version': '1.1.17'}
    if case == 'unexpected-name':
        request['files']['/dev/vda'] = 'a' * 64
    elif case == 'checksum':
        request['files']['Ubuntu.iso'] = 'a' * 64
    elif case == 'symlink':
        (tmp_path / 'Ubuntu.iso').unlink()
        (tmp_path / 'Ubuntu.iso').symlink_to(tmp_path / 'Apex-Live.iso')
    else:
        request['ventoy_version'] = '../../unsafe'
    with pytest.raises(RuntimeError):
        module.verify_inputs(tmp_path, request)


@pytest.mark.parametrize('case', ['valid', 'wrong-signer', 'bad-signature', 'wrong-name', 'changed-iso', 'wrong-size'])
def test_ubuntu_requires_signature_and_exact_pinned_iso(tmp_path, monkeypatch, case):
    module = fixture_module()
    iso, sums, signature, keyring = [tmp_path / name for name in ('Ubuntu.iso', 'SHA256SUMS', 'sig', 'keyring')]
    iso.write_bytes(b'Ubuntu fixture')
    expected = module.digest(iso)
    name = 'ubuntu-26.04-desktop-amd64.iso'
    signer = 'A' * 40
    sums.write_text(expected + '  ' + (name if case != 'wrong-name' else 'unrelated.iso') + '\n')
    signature.touch()
    keyring.touch()
    locked = {'sha256': expected, 'filename': name, 'signer': signer, 'bytes': iso.stat().st_size}
    if case == 'changed-iso':
        iso.write_bytes(b'Changed fixture')
    if case == 'wrong-size':
        locked['bytes'] += 1
    calls = []
    def fake_run(args, **kwargs):
        calls.append(args)
        identity = 'B' * 40 if case == 'wrong-signer' else signer
        return subprocess.CompletedProcess(args, 1 if case == 'bad-signature' else 0,
                                           '[GNUPG:] VALIDSIG ' + identity + ' 2026-09-09\n', '')
    monkeypatch.setattr('apexlib.ventoy.subprocess.run', fake_run)
    if case == 'valid':
        assert verify_ubuntu(iso, sums, signature, keyring, tmp_path, locked)['status'] == 'PASS'
    else:
        with pytest.raises(Blocked):
            verify_ubuntu(iso, sums, signature, keyring, tmp_path, locked)
    assert '--homedir' in calls[0]
    assert str(tmp_path / 'gpgv') in calls[0]
