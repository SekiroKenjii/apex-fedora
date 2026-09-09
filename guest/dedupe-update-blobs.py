#!/usr/bin/python3
"""Share identical blob extents in a completed fixture without removing files."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import stat
import struct
import subprocess
import tempfile

# Linux x86_64 UAPI: _IOWR(0x94, 54, struct file_dedupe_range).
FIDEDUPERANGE = 0xC0189436
HEADER = struct.Struct('=QQHHI')
INFO = struct.Struct('=qQQiI')
CHUNK = 16 * 1024**2


def request(source_fd, target_fd, offset, length):
    if offset < 0 or length <= 0 or offset % 4096 or length % 4096:
        raise ValueError('Dedupe ranges must use positive aligned lengths')
    buffer = bytearray(HEADER.pack(offset, length, 1, 0, 0) + INFO.pack(target_fd, offset, 0, 0, 0))
    fcntl.ioctl(source_fd, FIDEDUPERANGE, buffer, True)
    _, _, count, status, _ = INFO.unpack_from(buffer, HEADER.size)
    if status != 0 or count != length:
        raise ValueError(f'Dedupe rejected or incomplete: status={status}, bytes={count}/{length}')
    return count


def digest(path):
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOATIME | os.O_NOFOLLOW), 'rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def metadata(path):
    st = path.lstat()
    if not stat.S_ISREG(st.st_mode):
        raise ValueError('Only regular blob files are supported')
    return [st.st_dev, st.st_ino, st.st_size, st.st_mode, st.st_uid, st.st_gid, st.st_nlink]


def share(source, target):
    before = [metadata(source), metadata(target)]
    if before[0][0] != before[1][0] or before[0][2] != before[1][2]:
        raise ValueError('Blobs must have equal lengths on the same filesystem')
    expected = digest(source)
    if digest(target) != expected:
        raise ValueError('Blob contents differ')
    total = before[0][2] // 4096 * 4096
    with os.fdopen(os.open(source, os.O_RDONLY | os.O_NOATIME | os.O_NOFOLLOW), 'rb') as src:
        with os.fdopen(os.open(target, os.O_RDWR | os.O_NOATIME | os.O_NOFOLLOW), 'r+b') as dst:
            for offset in range(0, total, CHUNK):
                request(src.fileno(), dst.fileno(), offset, min(CHUNK, total - offset))
            os.fsync(dst.fileno())
    if before != [metadata(source), metadata(target)] or digest(source) != expected or digest(target) != expected:
        raise ValueError('Blob identity or content changed')
    return {'sha256': expected, 'bytes_submitted': total, 'tail_bytes_not_shared': before[0][2] - total,
            'identities_unchanged': True}


def self_test(directory):
    source, target, wrong = (directory / name for name in ('source', 'target', 'different'))
    content = os.urandom(1024**2)
    source.write_bytes(content)
    target.write_bytes(content)
    changed = bytes([content[0] ^ 1]) + content[1:]
    wrong.write_bytes(changed)
    shared = share(source, target)
    with source.open('rb') as src, wrong.open('r+b') as dst:
        try:
            request(src.fileno(), dst.fileno(), 0, 4096)
        except ValueError as error:
            if 'status=1,' not in str(error):
                raise
        else:
            raise ValueError('Kernel accepted nonidentical ranges')
    with target.open('r+b') as stream:
        stream.write(bytes([content[0] ^ 255]))
    if source.read_bytes() != content or target.read_bytes() == content or wrong.read_bytes() != changed:
        raise ValueError('Copy-on-write isolation failed')
    return {'identical': shared, 'kernel_rejected_difference': True, 'cow_write_isolation': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument('--self-test', action='store_true')
    choice.add_argument('--fixture')
    args = parser.parse_args()
    if (os.geteuid() or platform.machine() != 'x86_64'
            or Path('/etc/apex-builder').read_text().strip() != 'apex-isolated-builder-v1'
            or subprocess.check_output(['systemd-detect-virt', '--vm'], text=True).strip() not in {'kvm', 'qemu'}):
        raise ValueError('Use the isolated x86_64 Fedora builder')
    with Path('/run/apex-build.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if subprocess.check_output(['findmnt', '-n', '-o', 'FSTYPE', '-T', '/var/tmp'], text=True).strip() != 'btrfs':
            raise ValueError('The builder scratch filesystem must be Btrfs')
        if json.loads(subprocess.check_output(['podman', 'ps', '--format', 'json'], text=True)):
            raise ValueError('Stop build containers first')
        directory = Path(tempfile.mkdtemp(prefix='apex-dedupe-', dir='/var/tmp'))
        report = {'status': 'BLOCKED', 'files_removed': 0, 'files': {}, 'free_before': shutil.disk_usage(directory).free}
        print(directory, flush=True)
        def save():
            (directory / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
        try:
            report['self_test'] = self_test(directory)
            save()
            if args.fixture:
                if not re.fullmatch('[a-f0-9]{32}', args.fixture):
                    raise ValueError('Invalid completed fixture ID')
                root = Path('/var/tmp/apex-update-' + args.fixture)
                if root.resolve() != root:
                    raise ValueError('Fixture path must not redirect elsewhere')
                completed = json.loads((root / 'output/results.json').read_text())
                if completed['status'] != 'PASS' or completed['id'] != args.fixture:
                    raise ValueError('A completed fixture is required')
                report['fixture'] = args.fixture
                report['original_report_sha256'] = digest(root / 'output/results.json')
                source, target = root / 'bundle/b', root / 'wrong-signed'
                for path in (source, target):
                    if path.resolve() != path:
                        raise ValueError('Blob directories must not redirect elsewhere')
                names = {p.name for p in target.iterdir() if re.fullmatch('[a-f0-9]{64}', p.name)}
                if names != {p.name for p in source.iterdir() if re.fullmatch('[a-f0-9]{64}', p.name)}:
                    raise ValueError('Unexpected blob inventory')
                preserved = {str(p): digest(p) for base in (source, target) for p in base.iterdir() if p.name not in names}
                if 'sha256:' + preserved[str(source / 'manifest.json')] != completed['images']['b']['digest']:
                    raise ValueError('Unexpected B manifest')
                for name in sorted(names):
                    if digest(source / name) != name or digest(target / name) != name:
                        raise ValueError('Content-addressed blob checksum mismatch')
                    report['files'][name] = share(source / name, target / name)
                    save()
                if preserved != {name: digest(Path(name)) for name in preserved}:
                    raise ValueError('A manifest, signature or transport marker changed')
                report['preserved_sha256'] = preserved
            os.sync()
            report['free_after'] = shutil.disk_usage(directory).free
            report['status'] = 'PASS'
        except Exception as error:
            report['error'] = str(error)
            raise
        finally:
            save()


if __name__ == '__main__':
    main()
