"""Rebuild the reviewed Fedora fingerprint packages with Apex's experimental patches."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile


def sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def require_builder():
    marker = Path('/etc/apex-builder')
    if os.geteuid() != 0 or not marker.is_file() or marker.read_text().strip() != 'apex-isolated-builder-v1':
        raise RuntimeError('Fingerprint RPM build requires the isolated Fedora builder VM')
    if subprocess.check_output(['systemd-detect-virt', '--vm'], text=True).strip() not in {'kvm', 'qemu'}:
        raise RuntimeError('Fingerprint RPM build requires QEMU/KVM')
    release = Path('/etc/os-release').read_text().splitlines()
    if 'ID=fedora' not in release or 'VERSION_ID=44' not in release:
        raise RuntimeError('Fingerprint RPM build requires Fedora 44')
    if shutil.disk_usage(Path.cwd()).free < 24 * 1024**3:
        raise RuntimeError('Fingerprint RPM build needs 24 GiB free in the VM')


def prepare_spec(text, package, release):
    if text.count(package['prep']) != 1 or re.search(r'^Patch\d*:', text, re.M):
        raise ValueError('Unexpected source spec patch layout')
    if len(re.findall(r'^Release:\s+%autorelease$', text, re.M)) != 1:
        raise ValueError('Unexpected source spec release')
    text = re.sub(r'^Release:\s+%autorelease$', 'Release:        ' + release, text, flags=re.M)
    text = text.replace(package['prep'], package['prep_patched'])
    lines = text.splitlines(keepends=True)
    source = [i for i, line in enumerate(lines) if line.startswith('Source0:')]
    if len(source) != 1:
        raise ValueError('Expected one upstream source archive')
    lines.insert(source[0] + 1, f'Patch1000:      {Path(package["patch"]).name}\n')
    return ''.join(lines)


def validate_members(names, package):
    normalized = [name.removeprefix('./') for name in names]
    if (set(normalized) != {package['name'] + '.spec', package['archive']}
            or len(normalized) != 2):
        raise ValueError('Unexpected source RPM members')


def validate_patch_archive(archive, patch):
    # Catch patch format failures before Mock downloads build dependencies.
    with tempfile.TemporaryDirectory(prefix='apex-patch-check-') as temporary:
        root = Path(temporary)
        with tarfile.open(archive) as source:
            source.extractall(root, filter='data')
        trees = list(root.iterdir())
        if len(trees) != 1 or not trees[0].is_dir():
            raise ValueError('Unexpected upstream archive layout')
        tree = trees[0]
        subprocess.run(['git', 'apply', '--check', '-p1', str(patch.resolve())], cwd=tree, check=True)
        subprocess.run(['patch', '--dry-run', '--batch', '--fuzz=0', '-p1', '-i', str(patch.resolve())], cwd=tree, check=True)


def main():
    require_builder()
    lock_path = Path('config/fingerprint-rpms.lock.json')
    lock = json.loads(lock_path.read_text())
    if (lock['schema'] != 1 or lock['release'] != '1%{?dist}.apex1'
            or [p['name'] for p in lock['packages']] != ['libfprint', 'gnome-control-center']):
        raise ValueError('Unexpected fingerprint RPM lock')
    out = Path('output').resolve()
    out.mkdir(exist_ok=False)
    report = {'stage': 'rpm-build', 'status': 'FAIL', 'source_lock_sha256': sha256(lock_path),
              'source_trust': lock['source_trust'], 'packages': {}, 'ready_to_install': False,
              'hardware': 'NOT TESTED', 'image_integration': 'NOT TESTED',
              'full_gtk_dbus_integration': 'NOT TESTED', 'rpm_signatures': 'UNSIGNED'}
    try:
        for package in lock['packages']:
            name = package['name']
            work = out / name
            sources = work / 'sources'
            sources.mkdir(parents=True)
            srpm = work / (name + '.upstream.src.rpm')
            subprocess.run(['curl', '--fail', '--location', '--proto', '=https', '--proto-redir', '=https',
                            '--retry', '2', '--max-time', '600', package['url'], '-o', str(srpm)], check=True)
            if sha256(srpm) != package['sha256']:
                raise ValueError('Upstream source RPM checksum mismatch')
            cpio = subprocess.check_output(['rpm2cpio', str(srpm)])
            names = subprocess.check_output(['cpio', '-t', '--quiet'], input=cpio).decode().splitlines()
            validate_members(names, package)
            subprocess.run(['cpio', '-id', '--quiet', '--no-absolute-filenames'], input=cpio, cwd=sources, check=True)
            spec = sources / (name + '.spec')
            if sha256(spec) != package['spec_sha256'] or sha256(sources / package['archive']) != package['archive_sha256']:
                raise ValueError('Extracted source/spec checksum mismatch')
            original = spec.read_text()
            (work / 'upstream.spec').write_text(original)
            spec.write_text(prepare_spec(original, package, lock['release']))
            shutil.copyfile(package['patch'], sources / Path(package['patch']).name)
            validate_patch_archive(sources / package['archive'], sources / Path(package['patch']).name)
            entry = report['packages'][name] = {'status': 'FAIL', 'patch_sha256': sha256(Path(package['patch'])),
                                               'upstream_tests': package['upstream_tests']}
            mock = ['mock', '-r', 'fedora-44-x86_64', '--define', '_smp_mflags -j4', '--define', '_default_patch_fuzz 0']
            subprocess.run(mock + ['--buildsrpm', '--spec', str(spec), '--sources', str(sources),
                                   '--resultdir', str(work / 'srpm')], check=True)
            rebuilt = list((work / 'srpm').glob('*.src.rpm'))
            if len(rebuilt) != 1:
                raise ValueError('Expected one patched SRPM')
            subprocess.run(mock + ['--rebuild', str(rebuilt[0]), '--resultdir', str(work / 'mock')], check=True)
            rpms = [p for p in (work / 'mock').glob('*.rpm') if not p.name.endswith('.src.rpm')]
            if not rpms:
                raise ValueError('No binary RPMs produced')
            identities = {}
            for rpm in rpms:
                identity = subprocess.check_output(['rpm', '-qp', '--qf', '%{NAME}|%{VERSION}|%{RELEASE}|%{ARCH}', str(rpm)], text=True)
                fields = identity.split('|')
                if fields[1] != package['version'] or fields[2] != '1.fc44.apex1':
                    raise ValueError('Built RPM version differs from request')
                identities[rpm.name] = identity
            entry.update(status='PASS', rpms=identities)
        repo = out / 'packages'
        repo.mkdir()
        for package in lock['packages']:
            for rpm in (out / package['name'] / 'mock').glob('*.rpm'):
                if not rpm.name.endswith('.src.rpm') and '-debuginfo-' not in rpm.name and '-debugsource-' not in rpm.name:
                    shutil.copyfile(rpm, repo / rpm.name)
        subprocess.run(['createrepo_c', str(repo)], check=True)
        report['status'] = 'PASS'
    finally:
        report['artifacts'] = {str(p.relative_to(out)): sha256(p) for p in sorted(out.rglob('*')) if p.is_file() and p.name != 'results.json'}
        (out / 'results.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
