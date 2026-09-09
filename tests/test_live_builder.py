import hashlib
import importlib.util

import pytest
from apexlib.common import ROOT

spec = importlib.util.spec_from_file_location('live_builder', ROOT / 'guest/prepare-live-builder.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)
label_spec = importlib.util.spec_from_file_location('live_labels', ROOT / 'guest/prepare-live-rootfs.py')
labels = importlib.util.module_from_spec(label_spec)
label_spec.loader.exec_module(labels)


def test_preserve_ownership_and_export_filesystem_metadata(monkeypatch):
    source = b'#!/bin/bash\nmksquashfs /rootfs /work/iso-root/LiveOS/squashfs.img -all-root -noappend -comp zstd\n'
    monkeypatch.setattr(builder, 'UPSTREAM_SHA256', hashlib.sha256(source).hexdigest())
    result = builder.adapt(source)
    assert b'-all-root' not in result
    assert b'-noappend -mem 1G -processors 4 -comp zstd' in result
    assert b'python3 /apex-guest/prepare-live-rootfs.py\n' in result
    assert b'mksquashfs /work/live-rootfs ' in result
    assert result.splitlines()[1] == b'set -e -o pipefail'
    assert b'unsquashfs -lln' in result


def test_refuse_unreviewed_or_already_modified_builder():
    with pytest.raises(ValueError, match='pinned Titanoboa'):
        builder.adapt(b'arbitrary replacement')


def test_failure_stops_even_when_shebang_options_are_bypassed(tmp_path, monkeypatch):
    import subprocess
    source = (b'#!/bin/bash\nfalse\ntouch continued\n'
              b'mksquashfs /rootfs /work/iso-root/LiveOS/squashfs.img -all-root -noappend\n')
    monkeypatch.setattr(builder, 'UPSTREAM_SHA256', hashlib.sha256(source).hexdigest())
    result = subprocess.run(['bash'], input=builder.adapt(source), cwd=tmp_path, capture_output=True)
    assert result.returncode == 1
    assert not (tmp_path / 'continued').exists()


def test_live_rootfs_preparation_refuses_host():
    import subprocess
    import sys
    result = subprocess.run([sys.executable, ROOT / 'guest/prepare-live-rootfs.py'],
                            capture_output=True, text=True)
    assert result.returncode != 0
    assert 'isolated Fedora builder container' in result.stderr


def test_live_mount_and_initramfs_prerequisites():
    recipe = (ROOT / 'guest/live-artifact.sh').read_text()
    assert 'destination=/rootfs,rw=false' in recipe
    assert 'destination=/rootfs,ro=' not in recipe
    assert '-v "$PWD/live-work:/work"' in recipe
    setup = (ROOT / 'live/configure.sh').read_text()
    assert setup.index('install -d -m 0700 "$(realpath /root)"') < setup.index('dracut --force')


@pytest.mark.parametrize('actual', ['system_u:object_r:container_file_t:s0', None])
def test_container_or_missing_labels_cannot_pass(tmp_path, monkeypatch, actual):
    from types import SimpleNamespace
    monkeypatch.setattr(labels, 'PROBES', ('/',))
    monkeypatch.setattr(labels, 'invoke', lambda args: SimpleNamespace(stdout='system_u:object_r:root_t:s0\n'))

    def getxattr(*args, **kwargs):
        if actual is None:
            raise OSError('No security label')
        return actual.encode() + b'\0'

    monkeypatch.setattr(labels.os, 'getxattr', getxattr)
    with pytest.raises((RuntimeError, OSError)):
        labels.checked_labels(tmp_path, tmp_path / 'file_contexts')


def test_checked_labels_retain_numeric_ownership_and_mode(tmp_path, monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(labels, 'PROBES', ('/',))
    monkeypatch.setattr(labels, 'invoke', lambda args: SimpleNamespace(stdout='system_u:object_r:root_t:s0\n'))
    monkeypatch.setattr(labels.os, 'getxattr', lambda *args, **kwargs: b'system_u:object_r:root_t:s0\0')
    report = labels.checked_labels(tmp_path, tmp_path / 'file_contexts')['/']
    assert report['uid'] == tmp_path.stat().st_uid
    assert report['gid'] == tmp_path.stat().st_gid
    assert report['mode'] == oct(tmp_path.stat().st_mode & 0o7777)


def test_copy_excludes_ostree_and_separates_hardlink_metadata(tmp_path, monkeypatch):
    import os
    source = tmp_path / 'source'
    target = tmp_path / 'target'
    source.mkdir(mode=0o755)
    for name in ('sysroot', 'ostree', 'usr'):
        (source / name).mkdir()
    (source / 'usr/one').write_text('same content')
    os.link(source / 'usr/one', source / 'usr/two')
    monkeypatch.setattr(labels.os, 'chown', lambda *args: None)
    labels.copy_tree(source, target)
    assert not (target / 'sysroot').exists() and not (target / 'ostree').exists()
    assert (target / 'usr/one').read_bytes() == (target / 'usr/two').read_bytes()
    assert (target / 'usr/one').stat().st_ino != (target / 'usr/two').stat().st_ino
    assert (source / 'usr/one').stat().st_ino == (source / 'usr/two').stat().st_ino
