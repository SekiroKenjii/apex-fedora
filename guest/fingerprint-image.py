"""Derive a development image from a frozen payload using tested fingerprint RPMs."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

ALLOWED_PACKAGES = {'libfprint', 'gnome-control-center', 'gnome-control-center-filesystem'}
PROTECTED = ('/usr/lib/modules', '/usr/lib/firmware', '/etc/modprobe.d', '/usr/lib/modprobe.d',
             '/etc/NetworkManager/conf.d', '/usr/lib/NetworkManager/conf.d')


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def package_delta(before, after):
    def parse(text):
        rows = [line.split('|') for line in text.splitlines()]
        if any(len(row) != 2 for row in rows) or len({row[0] for row in rows}) != len(rows):
            raise ValueError('Invalid RPM inventory')
        return dict(rows)
    left, right = parse(before), parse(after)
    if left.keys() != right.keys():
        raise ValueError('Fingerprint integration added or removed a package')
    changed = {name: {'before': left[name], 'after': right[name]}
               for name in left if left[name] != right[name]}
    if set(changed) != ALLOWED_PACKAGES:
        raise ValueError('Unexpected package changes: ' + ', '.join(sorted(changed)))
    for name, change in changed.items():
        if change['after'] != change['before'].replace('-1.fc44.', '-1.fc44.apex1.'):
            raise ValueError('Fingerprint integration changed a vendor version')
    return changed


def main():
    root = Path.cwd()
    if (os.geteuid() != 0 or Path('/etc/apex-builder').read_text().strip() != 'apex-isolated-builder-v1'
            or not re.fullmatch(r'/var/tmp/apex-[a-f0-9]{32}', str(root))
            or subprocess.check_output(['systemd-detect-virt', '--vm'], text=True).strip() not in {'kvm', 'qemu'}):
        raise RuntimeError('Requires an allocated directory in the isolated builder VM')
    if shutil.disk_usage(root).free < 24 * 1024**3:
        raise RuntimeError('Need 24 GiB free in the builder')
    request = json.loads(Path('fingerprint-request.json').read_text())
    for name, checksum in request['rpms'].items():
        if not re.fullmatch(r'[a-z0-9._-]+\.rpm', name) or sha(root / 'inputs' / name) != checksum:
            raise ValueError('Fingerprint RPM input checksum mismatch')
    parent = json.loads(Path('target-image.json').read_text())
    if parent['profile'] != 'fedora':
        raise ValueError('Fingerprint experiment requires the Fedora control profile')
    tag_parent = 'localhost/apex-payload:' + parent['digest'].removeprefix('sha256:')
    output = root / 'output'
    output.mkdir(exist_ok=True)
    report = {'status': 'FAIL', 'parent': parent, 'rpm_build': request['rpm_build'],
              'gtk_test': request['gtk_test'], 'rpm_sha256': request['rpms'],
              'rpm_signature_policy': 'unsigned development inputs verified by pinned build checksums',
              'hardware': 'NOT TESTED', 'boot': 'NOT TESTED', 'commands': []}

    def save():
        (output / 'fingerprint-integration.json').write_text(json.dumps(report, indent=2) + '\n')

    def command(args, timeout=600):
        print('Running:', ' '.join(map(str, args[:5])), flush=True)
        index = len(report['commands'])
        stdout = output / f'command-{index}.stdout'
        stderr = output / f'command-{index}.stderr'
        with stdout.open('w') as out, stderr.open('w') as err:
            result = subprocess.run(list(map(str, args)), stdout=out, stderr=err, text=True, timeout=timeout)
        result.stdout, result.stderr = stdout.read_text(), stderr.read_text()
        report['commands'].append({'argv': list(map(str, args)), 'returncode': result.returncode,
                                   'stdout': result.stdout, 'stderr': result.stderr})
        save()
        if result.returncode:
            raise RuntimeError('Image command failed; see fingerprint-integration.json')
        return result.stdout

    try:
        raw = command(['skopeo', 'inspect', '--raw', 'containers-storage:' + tag_parent])
        if 'sha256:' + hashlib.sha256(raw.encode()).hexdigest() != parent['digest']:
            raise ValueError('Parent manifest changed')
        query = ['rpm', '-qa', '--qf', '%{NAME}|%{EPOCHNUM}:%{VERSION}-%{RELEASE}.%{ARCH}\n']
        before = command(['podman', 'run', '--rm', '--network=none', tag_parent, *query])
        context = root / 'context'
        context.mkdir()
        for name in request['rpms']:
            shutil.copyfile(root / 'inputs' / name, context / name)
        shutil.copyfile(root / 'guest/fix-grub-fragment.py', context / 'fix-grub-fragment.py')
        preset = root / 'system_files/usr/share/apex/greenboot.conf'
        if 'GREENBOOT_MAX_BOOT_ATTEMPTS=1\n' not in preset.read_text():
            raise ValueError('Expected the tested one-retry recovery preset')
        shutil.copyfile(preset, context / 'greenboot.conf')
        recipe = (f'FROM {tag_parent}\nCOPY *.rpm /tmp/fingerprint-rpms/\n'
                  'RUN dnf -y --disable-repo="*" --setopt=install_weak_deps=False --nogpgcheck '
                  'install /tmp/fingerprint-rpms/*.rpm && rm -r /tmp/fingerprint-rpms '
                  '/run/dnf /var/cache/libdnf5 && rm -f /var/cache/ldconfig/aux-cache /var/log/dnf5.log\n'
                  'COPY greenboot.conf /usr/share/apex/greenboot.conf\n'
                  'COPY greenboot.conf /etc/greenboot/greenboot.conf\n'
                  'COPY fix-grub-fragment.py /tmp/fix-grub-fragment.py\n'
                  'RUN python3 /tmp/fix-grub-fragment.py /usr/lib/bootupd/grub2-static/configs.d/08_greenboot.cfg '
                  '> /usr/share/apex/greenboot-fragment.json && rm /tmp/fix-grub-fragment.py\n')
        (context / 'Containerfile').write_text(recipe)
        (output / 'Containerfile').write_text(recipe)
        tag = 'localhost/apex-fingerprint:' + root.name.removeprefix('apex-')
        command(['podman', 'build', '--network=none', '--pull=never', '--layers=false', '-t', tag, context])
        after = command(['podman', 'run', '--rm', '--network=none', tag, *query])
        report['package_delta'] = package_delta(before, after)
        (output / 'parent-rpms.txt').write_text('\n'.join(sorted(before.splitlines())) + '\n')
        (output / 'image-rpms.txt').write_text('\n'.join(sorted(after.splitlines())) + '\n')
        probe = ('import hashlib,json,pathlib; result={}; '
                 f'roots={PROTECTED!r}; '
                 '\nfor root in roots:\n'
                 ' for p in sorted(pathlib.Path(root).rglob("*")):\n'
                 '  if p.is_symlink(): result[str(p)]="link:"+str(p.readlink())\n'
                 '  elif p.is_file():\n'
                 '   with p.open("rb") as f: result[str(p)]=hashlib.file_digest(f,"sha256").hexdigest()\n'
                 'print(json.dumps(result,sort_keys=True))')
        protected = []
        for name in (tag_parent, tag):
            protected.append(json.loads(command(['podman', 'run', '--rm', '--read-only', '--network=none',
                                                  name, 'python3', '-c', probe])))
        if not protected[0] or protected[0] != protected[1]:
            raise ValueError('Kernel, firmware or driver configuration changed')
        report['protected_file_count'] = len(protected[0])
        (output / 'protected-files.json').write_text(json.dumps(protected[0], sort_keys=True, indent=2) + '\n')
        command(['podman', 'run', '--rm', '--network=none', tag, 'bootc', 'container', 'lint', '--fatal-warnings'])
        command(['podman', 'save', '--format=oci-archive', '--output', output / 'apex-fedora.oci.tar', tag], timeout=900)
        manifest = command(['skopeo', 'inspect', '--raw', 'oci-archive:' + str(output / 'apex-fedora.oci.tar')])
        (output / 'manifest.json').write_text(manifest)
        image_id = json.loads(manifest)['config']['digest']
        digest = 'sha256:' + hashlib.sha256(manifest.encode()).hexdigest()
        image = {'image_id': image_id, 'digest': digest, 'profile': 'fedora', 'parent_digest': parent['digest'],
                 'experiment': 'fingerprint-apex1', 'ready_to_install': False}
        (output / 'image.json').write_text(json.dumps(image, indent=2) + '\n')
        command(['bash', 'guest/import-payload.sh', output / 'apex-fedora.oci.tar', output / 'image.json'])
        shutil.copyfile('config/sources.lock.json', output / 'sources.lock.json')
        report['digest'] = digest
        report['status'] = 'PASS'
        save()
        subprocess.run(['python3', 'guest/sign-artifacts.py', output, output / 'image.json'], check=True)
    except Exception:
        report['status'] = 'FAIL'
        save()
        raise


if __name__ == '__main__':
    main()
