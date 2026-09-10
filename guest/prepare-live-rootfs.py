#!/usr/bin/python3
"""Label a separate live tree on the Fedora builder's scratch filesystem."""
import json
import hashlib
import os
from pathlib import Path
import stat
import subprocess
import sys

SOURCE = Path('/rootfs')
TARGET = Path('/work/live-rootfs')
REPORT = Path('/output/rootfs-labeling.json')
PROBES = ('/', '/etc', '/etc/shadow', '/usr/bin/bash', '/usr/bin/passwd',
          '/usr/lib/systemd/systemd', '/usr/libexec/flatpak-system-helper',
          '/var', '/var/roothome')
EXCLUDED = {'sysroot', 'ostree'}


def invoke(args):
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode:
        failure = REPORT.with_name('rootfs-failure.json')
        failure.write_text(json.dumps({'command': args, 'returncode': result.returncode,
                           'stdout': result.stdout, 'stderr': result.stderr}, indent=2) + '\n')
        raise RuntimeError(f'{args[0]} failed; full output in {failure}: {result.stderr[:2048]}')
    return result


def copy_tree(source, target):
    target.mkdir(mode=0o700)
    # OSTree object paths share inodes with deployed files but need different labels.
    # Match Titanoboa's exclusions and give every included path independent metadata.
    for path in sorted(source.iterdir()):
        if path.name not in EXCLUDED:
            invoke(['cp', '-a', '--no-preserve=links', '--reflink=auto', str(path), str(target)])
    source_info = source.stat()
    os.chown(target, source_info.st_uid, source_info.st_gid)
    os.chmod(target, stat.S_IMODE(source_info.st_mode))


def prepare_labeler():
    # Mirror osbuild's install_exec_t transition in this VM-only mount namespace.
    # install_t can write labels from the target policy that the builder lacks.
    directory = Path('/run/apex-labeler')
    directory.mkdir(mode=0o700)
    invoke(['mount', '-t', 'tmpfs', '-o', 'mode=0700', 'tmpfs', str(directory)])
    executable = directory / 'setfiles'
    invoke(['cp', '-p', '/usr/bin/setfiles', str(executable)])
    invoke(['chcon', 'system_u:object_r:install_exec_t:s0', str(executable)])
    return executable


def checked_labels(root, contexts):
    result = {}
    for relative in PROBES:
        path = root / relative.lstrip('/')
        expected = invoke(['matchpathcon', '-N', '-n', '-f', str(contexts), relative]).stdout.strip()
        actual = os.getxattr(path, 'security.selinux', follow_symlinks=False).rstrip(b'\0').decode()
        if actual != expected:
            raise RuntimeError(f'Wrong SELinux label at {relative}: {actual}, expected {expected}')
        info = path.lstat()
        result[relative] = {'label': actual, 'uid': info.st_uid, 'gid': info.st_gid,
                            'mode': oct(stat.S_IMODE(info.st_mode))}
        if stat.S_ISREG(info.st_mode):
            with path.open('rb') as stream:
                result[relative]['sha256'] = hashlib.file_digest(stream, 'sha256').hexdigest()
    return result


def require_environment():
    if (os.geteuid() != 0 or not Path('/run/.containerenv').is_file()
            or not Path('/run/apex-builder').is_file()
            or Path('/run/apex-builder').read_text().strip() != 'apex-isolated-builder-v1'):
        raise RuntimeError('Requires the isolated Fedora builder container')
    domain = Path('/proc/self/attr/current').read_text().rstrip('\0\n').split(':')
    if len(domain) < 3 or domain[2] != 'install_t':
        raise RuntimeError('Live label readers must run in install_t')


def verify_packed():
    require_environment()
    prepared = json.loads(REPORT.read_text())
    if prepared.get('status') != 'PASS':
        raise RuntimeError('Live scratch labeling did not pass')
    contexts = TARGET / 'etc/selinux/targeted/contexts/files/file_contexts'
    extracted = checked_labels(Path('/work/live-label-check'), contexts)
    if extracted != prepared['critical_paths']:
        raise RuntimeError('Squashfs changed critical-file labels, ownership, mode or content')
    with Path('/work/iso-root/LiveOS/squashfs.img').open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    REPORT.with_name('squashfs-verification.json').write_text(json.dumps({
        'status': 'PASS', 'scope': 'Extracted critical-path metadata and content',
        'squashfs_sha256': digest, 'critical_paths': extracted,
        'boot_acceptance': 'NOT TESTED'}, indent=2) + '\n')


def prepare():
    require_environment()
    if TARGET.exists() or TARGET.is_symlink():
        raise RuntimeError('Preserving an existing live scratch tree; start a fresh build')
    if not os.path.ismount('/work'):
        raise RuntimeError('Live scratch must be a separate VM filesystem mount')
    options = invoke(['findmnt', '-n', '-o', 'OPTIONS', '-T', '/work']).stdout.strip()
    if 'context=' in options or 'seclabel' not in options.split(','):
        raise RuntimeError('Live scratch does not support independent SELinux file labels')
    copy_tree(SOURCE, TARGET)
    contexts = TARGET / 'etc/selinux/targeted/contexts/files/file_contexts'
    policies = sorted((TARGET / 'etc/selinux/targeted/policy').glob('policy.*'))
    if len(policies) != 1 or not contexts.is_file() or not policies[0].is_file():
        raise RuntimeError('Expected one compiled targeted policy in the live tree')
    labeler = prepare_labeler()
    command = [str(labeler), '-F', '-c', str(policies[0]), '-r', str(TARGET), str(contexts), str(TARGET)]
    labeled = invoke(command)
    verified = invoke(command[:1] + ['-n', '-v'] + command[1:])
    if verified.stdout.strip() or verified.stderr.strip():
        raise RuntimeError('Live tree still needs relabeling: ' + verified.stdout + verified.stderr)
    report = {'status': 'PASS', 'scope': 'live scratch SELinux labels before squashfs',
              'excluded_top_level': sorted(EXCLUDED), 'preserve_hardlinks': False,
              'scratch_mount_options': options, 'label_command': command,
              'label_stdout': labeled.stdout, 'label_stderr': labeled.stderr,
              'critical_paths': checked_labels(TARGET, contexts), 'boot_acceptance': 'NOT TESTED'}
    REPORT.write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    if sys.argv[1:] == ['--verify-squashfs']:
        verify_packed()
    elif not sys.argv[1:]:
        prepare()
    else:
        raise RuntimeError('Use no arguments or --verify-squashfs')
