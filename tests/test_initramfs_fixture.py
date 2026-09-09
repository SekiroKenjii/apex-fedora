import importlib.util
from pathlib import Path

import pytest


def module():
    spec = importlib.util.spec_from_file_location('initramfs_fixture', Path(__file__).resolve().parents[1] / 'guest/initramfs-fixture.py')
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def entry():
    return ('title test B\nversion 2\noptions rw ostree=/ostree/boot.0/default/' + 'a' * 64
            + '/0\nlinux /boot/ostree/example/vmlinuz\ninitrd /boot/ostree/example/initramfs.img\n')


def test_only_initrd_field_is_changed():
    m = module()
    target = '/apex-initramfs-fault/' + 'b' * 32 + '/bad.img'
    original = entry()
    result = m.modified_entry(original, target)
    assert result == original.replace('/boot/ostree/example/initramfs.img', target)
    assert m.parse_entry(original)['version'] == '2'


@pytest.mark.parametrize('suffix', ['initrd /another.img\n', 'options root=/dev/vda\n', 'efi /efi.efi\n'])
def test_rejects_duplicate_or_unknown_bls_fields(suffix):
    with pytest.raises(ValueError):
        module().parse_entry(entry() + suffix)


@pytest.mark.parametrize('value', ['/tmp/image', '/boot/ostree/../image', '/boot/ostree/$var',
                                 '/boot/ostree/a /boot/ostree/b', '/boot/ostree/a;touch'])
def test_rejects_unsafe_or_multiple_initrd_paths(value):
    with pytest.raises(ValueError):
        module().parse_entry(entry().replace('/boot/ostree/example/initramfs.img', value))


@pytest.mark.parametrize('value', ['/ostree/boot.0/../deploy/a/0', '/ostree/boot.0/default/a/0', 'relative'])
def test_rejects_ambiguous_bootlinks(value):
    with pytest.raises(ValueError):
        module().parse_entry(entry().replace('/ostree/boot.0/default/' + 'a' * 64 + '/0', value))


@pytest.mark.parametrize('path', ['/boot/real.img', '/apex-initramfs-fault/../bad.img',
                                '/apex-initramfs-fault/' + 'B' * 32 + '/bad.img'])
def test_refuses_writes_to_any_other_fault_path(path):
    with pytest.raises(ValueError):
        module().modified_entry(entry(), path)


def test_refuses_changed_plan_before_file_operations():
    with pytest.raises(ValueError, match='plan'):
        module().inject({}, 'a' * 32, 'changed')


def test_plan_hash_binds_content_and_identity():
    m = module()
    assert m.plan_hash({'a': 1, 'b': 2}) == m.plan_hash({'b': 2, 'a': 1})
    assert m.plan_hash({'inode': 1}) != m.plan_hash({'inode': 2})


def test_refuses_symlink_final_files(tmp_path):
    file = tmp_path / 'real'
    file.write_text('data')
    link = tmp_path / 'link'
    link.symlink_to(file)
    with pytest.raises(ValueError, match='regular'):
        module().fingerprint(link)


def test_rejects_non_root_before_vm_or_disk_operations(monkeypatch):
    m = module()
    monkeypatch.setattr(m.os, 'geteuid', lambda: 1000)
    monkeypatch.setattr(m, 'run', lambda *args: pytest.fail('Host command attempted'))
    with pytest.raises(ValueError, match='Root inside'):
        m.inspect('sha256:' + 'a' * 64, 'sha256:' + 'b' * 64)


def test_protected_file_drift_blocks_before_mount_or_fault_write(tmp_path, monkeypatch):
    m = module()
    source = tmp_path / 'initrd'
    source.write_bytes(b'x' * 8192)
    plan = {'entries': {'b': {'files': {'initrd': str(source)}, 'text': entry()}},
            'protected': {str(source): m.fingerprint(source)}}
    reviewed = m.plan_hash(plan)
    source.write_bytes(b'y' * 8192)
    monkeypatch.setattr(m, 'run', lambda *args: pytest.fail('Mount or mutation attempted'))
    with pytest.raises(ValueError, match='protected input changed'):
        m.inject(plan, 'b' * 32, reviewed)


@pytest.mark.parametrize('virt', ['none', 'docker', 'wsl'])
def test_root_outside_qemu_is_rejected_before_file_access(monkeypatch, virt):
    m = module()
    monkeypatch.setattr(m.os, 'geteuid', lambda: 0)
    def run(*args):
        assert args == ('systemd-detect-virt', '--vm')
        return virt
    monkeypatch.setattr(m, 'run', run)
    with pytest.raises(ValueError, match='Root inside'):
        m.inspect('sha256:' + 'a' * 64, 'sha256:' + 'b' * 64)
