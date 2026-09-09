"""Build a driver RPM set in the isolated VM without installing it in an image."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

REPOSITORY = 'https://developer.download.nvidia.com/compute/cuda/repos/fedora44/x86_64/'
NAMES = {'nvidia-driver', 'nvidia-driver-common', 'nvidia-driver-libs',
         'nvidia-driver-cuda', 'nvidia-driver-cuda-libs', 'nvidia-kmod-common',
         'nvidia-modprobe', 'nvidia-persistenced', 'nvidia-driver-selinux'}


def command(*args):
    return subprocess.check_output([str(x) for x in args], text=True).strip()


def require_builder():
    marker = Path('/etc/apex-builder')
    if os.geteuid() != 0 or not marker.is_file() or marker.read_text().strip() != 'apex-isolated-builder-v1':
        raise RuntimeError('NVIDIA build requires the isolated Fedora builder VM')
    if command('systemd-detect-virt', '--vm') not in {'kvm', 'qemu'}:
        raise RuntimeError('NVIDIA build requires QEMU/KVM')
    release = Path('/etc/os-release').read_text().splitlines()
    if 'ID=fedora' not in release or 'VERSION_ID=44' not in release:
        raise RuntimeError('NVIDIA build requires Fedora 44')
    if shutil.disk_usage(Path.cwd()).free < 24 * 1024 ** 3:
        raise RuntimeError('NVIDIA build needs at least 24 GiB free in the VM')


def validate_lock(lock):
    if lock.get('schema') != 1 or lock.get('repository') != REPOSITORY:
        raise ValueError('Unknown NVIDIA lock schema or repository')
    for key in ('version', 'kernel_release', 'kernel_devel_evr', 'compiler_evr'):
        if not re.fullmatch(r'[0-9][a-zA-Z0-9._+-]+', lock.get(key, '')):
            raise ValueError('Invalid locked version')
    if (lock.get('epoch') != '3' or lock['kernel_release'] != lock['kernel_devel_evr'] + '.x86_64'
            or not lock['kernel_devel_evr'].endswith('.fc44')
            or not lock['compiler_evr'].endswith('.fc44')
            or not isinstance(lock.get('compiler_text'), str) or '\n' in lock['compiler_text']):
        raise ValueError('Invalid kernel/compiler identity')
    source = lock['source']
    if (not re.fullmatch(r'[a-f0-9]{40}', source['commit'])
            or source['url'] != 'https://codeload.github.com/NVIDIA/open-gpu-kernel-modules/tar.gz/' + source['commit']
            or source['filename'] != 'open-gpu-kernel-modules.tar.gz'):
        raise ValueError('NVIDIA source must name a full commit')
    key = lock['signing_key']
    if not re.fullmatch(r'[A-F0-9]{40}', key['fingerprint']) or key['filename'] != key['fingerprint'][-8:] + '.pub':
        raise ValueError('Invalid NVIDIA key identity')
    packages = lock['packages']
    if len(packages) != len(NAMES) or {p['name'] for p in packages} != NAMES:
        raise ValueError('Unexpected or duplicate NVIDIA package')
    for package in packages:
        policy = package['name'] == 'nvidia-driver-selinux'
        expected_arch = 'noarch' if package['name'] in {'nvidia-kmod-common', 'nvidia-driver-selinux'} else 'x86_64'
        if (package['arch'] != expected_arch
                or not re.fullmatch(r'[0-9]+\.fc44', package['release'])
                or (not policy and (package['epoch'], package['version']) != ('3', lock['version']))
                or (policy and (package['epoch'], package['version']) != ('0', '0.1'))):
            raise ValueError('NVIDIA userspace/firmware version mismatch')
    for item in [source, key, *packages]:
        if not re.fullmatch(r'[a-f0-9]{64}', item['sha256']):
            raise ValueError('Missing SHA-256 pin')
    if lock['modules'] != ['nvidia', 'nvidia_modeset', 'nvidia_drm', 'nvidia_uvm']:
        raise ValueError('Unexpected module set')
    if lock['firmware'] != ['gsp_ga10x.bin', 'gsp_tu10x.bin', 'ucodes_ga10x.bin', 'ucodes_tu10x.bin']:
        raise ValueError('Unexpected firmware set')


def checksum(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def fetch(url, destination, expected):
    if destination.exists() or destination.is_symlink():
        raise ValueError('NVIDIA inputs require a fresh destination')
    subprocess.run(['curl', '--fail', '--location', '--proto', '=https', '--proto-redir', '=https',
                    '--retry', '2', '--connect-timeout', '20', '--max-time', '900',
                    url, '--output', str(destination)], check=True)
    if checksum(destination) != expected:
        raise ValueError('NVIDIA input checksum mismatch')


def filename(package):
    return '{name}-{version}-{release}.{arch}.rpm'.format(**package)


def rpm_identity(package):
    return '{name}|{epoch}|{version}|{release}|{arch}'.format(**package)


def require_signature(text):
    # rpmkeys can report success for a digest-only, unsigned package.
    lines = text.lower().splitlines()
    if (not any('signature' in line and line.strip().endswith(': ok') for line in lines)
            or any(word in text.lower() for word in ('not ok', 'nokey', 'nottrusted', 'bad'))):
        raise ValueError('RPM needs a valid signature from the pinned NVIDIA key')


def verify_vendor(path, package, db):
    signature = command('rpmkeys', '--dbpath', db, '--checksig', '--verbose', path)
    require_signature(signature)
    identity = command('rpm', '-qp', '--qf', '%{NAME}|%{EPOCHNUM}|%{VERSION}|%{RELEASE}|%{ARCH}', path)
    if identity != rpm_identity(package):
        raise ValueError('Signed RPM does not match the locked NEVRA')
    return {'identity': identity, 'signature': signature}


def main():
    require_builder()
    lock = json.loads(Path('config/nvidia.lock.json').read_text())
    validate_lock(lock)
    image = sys.argv[1]
    if not re.fullmatch(r'sha256:[a-f0-9]{64}', image):
        raise ValueError('A frozen OCI image ID is required')
    podman = ['podman', 'run', '--rm', '--read-only', '--network', 'none']
    kernel = command(*podman, '--entrypoint', 'rpm', image, '-q', 'kernel-core',
                     '--qf', '%{VERSION}-%{RELEASE}.%{ARCH}\n')
    if kernel != lock['kernel_release']:
        raise ValueError('Frozen image kernel differs from the reviewed NVIDIA lock')
    kernel_config = command(*podman, '--entrypoint', 'cat', image, f'/usr/lib/modules/{kernel}/config')
    if re.findall(r'^CONFIG_CC_VERSION_TEXT="([^"]+)"$', kernel_config, re.M) != [lock['compiler_text']]:
        raise ValueError('Frozen image compiler differs from the reviewed lock')
    out = Path('output/nvidia').resolve()
    out.mkdir(parents=True, exist_ok=False)
    sources = out / 'sources'
    packages = out / 'packages'
    sources.mkdir()
    packages.mkdir()
    shutil.copyfile('config/nvidia.lock.json', sources / 'nvidia.lock.json')
    shutil.copyfile('guest/nvidia-check.py', sources / 'nvidia-check.py')
    source = lock['source']
    fetch(source['url'], sources / source['filename'], source['sha256'])
    key = lock['signing_key']
    key_path = sources / key['filename']
    fetch(REPOSITORY + key['filename'], key_path, key['sha256'])
    checked = {}
    with tempfile.TemporaryDirectory(prefix='apex-nvidia-trust-') as trust:
        trust = Path(trust)
        gpg = trust / 'gnupg'
        gpg.mkdir(mode=0o700)
        fingerprints = command('gpg', '--batch', '--homedir', gpg, '--show-keys', '--with-colons', key_path)
        if [row.split(':')[9] for row in fingerprints.splitlines() if row.startswith('fpr:')] != [key['fingerprint']]:
            raise ValueError('NVIDIA key fingerprint mismatch')
        db = trust / 'rpmdb'
        db.mkdir(mode=0o700)
        command('rpm', '--dbpath', db, '--initdb')
        command('rpmkeys', '--dbpath', db, '--import', key_path)
        for package in lock['packages']:
            path = packages / filename(package)
            fetch(REPOSITORY + path.name, path, package['sha256'])
            checked[package['name']] = verify_vendor(path, package, db)
            # Retain policy, dependencies and scriptlets for image-integration review.
            for option, suffix in (('--scripts', 'scripts'), ('--requires', 'requires'), ('--list', 'files')):
                (out / (package['name'] + '.' + suffix + '.txt')).write_text(command('rpm', '-qp', option, path) + '\n')
    common = (out / 'nvidia-kmod-common.files.txt').read_text().splitlines()
    if not {f'/usr/lib/firmware/nvidia/{lock["version"]}/{name}' for name in lock['firmware']} <= set(common):
        raise ValueError('Matching GSP firmware is absent from the locked RPM')
    mock = ['mock', '-r', 'fedora-44-x86_64']
    for name, value in {'kernel_release': lock['kernel_release'], 'kernel_devel_evr': lock['kernel_devel_evr'],
                        'compiler_evr': lock['compiler_evr'], 'nvidia_version': lock['version'],
                        'nvidia_commit': source['commit']}.items():
        mock += ['--define', f'apex_{name} {value}']
    subprocess.run(mock + ['--buildsrpm', '--spec', str(Path('rpms/kmod-apex-nvidia-open.spec').resolve()),
                          '--sources', str(sources), '--resultdir', str(out / 'srpm')], check=True)
    srpms = list((out / 'srpm').glob('*.src.rpm'))
    if len(srpms) != 1:
        raise ValueError('Expected one NVIDIA SRPM')
    subprocess.run(mock + ['--rebuild', str(srpms[0]), '--resultdir', str(out / 'mock')], check=True)
    built = [p for p in (out / 'mock').glob('*.rpm') if not p.name.endswith('.src.rpm')]
    if len(built) != 1 or not built[0].name.startswith('kmod-apex-nvidia-open-'):
        raise ValueError('Unexpected NVIDIA build output')
    shutil.copyfile(built[0], packages / built[0].name)
    subprocess.run(['createrepo_c', str(packages)], check=True)
    artifacts = {str(p.relative_to(out)): checksum(p) for p in sorted(out.rglob('*')) if p.is_file()}
    report = {'status': 'PASS', 'stage': 'rpm-build', 'image_id': image,
              'kernel_release': kernel, 'version': lock['version'], 'vendor_rpms': checked,
              'artifacts': artifacts, 'source_lock_sha256': checksum(Path('config/nvidia.lock.json')),
              'image_integration': 'NOT TESTED', 'initramfs': 'NOT TESTED', 'hardware': 'NOT TESTED',
              'secure_boot': 'NOT TESTED', 'ready_to_install': False}
    (out / 'results.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
