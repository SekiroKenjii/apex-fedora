"""Exercise the rebuilt library's fake-device C tests inside the Fedora VM."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess


def checksum(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def tap_passed(text, returncode):
    plans = re.findall(r'^1\.\.(\d+)$', text, re.M)
    successes = re.findall(r'^ok \d+\b.*$', text, re.M)
    return (returncode == 0 and len(plans) == 1 and int(plans[0]) > 0
            and len(successes) == int(plans[0]) and not re.search(r'#\s*(SKIP|TODO)', text, re.I)
            and not re.search(r'^(not ok|Bail out!)', text, re.M))


def main():
    marker = Path('/etc/apex-builder')
    if os.geteuid() != 0 or not marker.is_file() or marker.read_text().strip() != 'apex-isolated-builder-v1':
        raise RuntimeError('Requires the isolated Fedora builder VM')
    if subprocess.check_output(['systemd-detect-virt', '--vm'], text=True).strip() not in {'kvm', 'qemu'}:
        raise RuntimeError('Requires QEMU/KVM')
    out = Path('output')
    out.mkdir(exist_ok=False)
    packages = [Path('inputs') / f'{name}-1.94.100-1.fc44.apex1.x86_64.rpm' for name in ('libfprint', 'libfprint-tests')]
    expected = json.loads(Path('inputs.json').read_text())
    if {p.name for p in packages} != set(expected):
        raise ValueError('Unexpected package input set')
    for path in packages:
        if path.is_symlink() or not path.is_file() or checksum(path) != expected[path.name]:
            raise ValueError('Package input checksum mismatch')
        identity = subprocess.check_output(['rpm', '-qp', '--qf', '%{NAME}-%{VERSION}-%{RELEASE}.%{ARCH}.rpm', str(path)], text=True)
        if identity != path.name:
            raise ValueError('Package identity mismatch')
    report = {'status': 'FAIL', 'rpm_sha256': expected, 'cases': {}, 'hardware': 'NOT TESTED',
              'gtk_dbus_integration': 'NOT TESTED', 'scope': 'installed libfprint C tests with fake devices, no sensor passthrough'}
    try:
        with (out / 'install.log').open('wb') as log:
            subprocess.run(['dnf5', '-y', '--disablerepo=*', 'install', *map(lambda p: str(p.resolve()), packages)],
                           stdout=log, stderr=subprocess.STDOUT, check=True)
        report['installed'] = subprocess.check_output(['rpm', '-q', 'libfprint', 'libfprint-tests', 'fprintd'], text=True).splitlines()
        for name in ('fpi-ssm', 'fpi-device'):
            result = subprocess.run(['runuser', '-u', 'builder', '--', 'env', '-u', 'FP_DEBUG_TRANSFER',
                                     '-u', 'G_MESSAGES_DEBUG', '-u', 'APEX_ELAN_STATUS_DIAGNOSTICS',
                                     'G_DEBUG=fatal-warnings', 'FP_DEVICE_EMULATION=1',
                                     'FP_DRIVERS_ALLOWLIST=virtual_device:virtual_device_storage:virtual_image',
                                     '/usr/libexec/installed-tests/libfprint-2/test-' + name, '--tap'],
                                    text=True, capture_output=True, timeout=180)
            (out / (name + '.log')).write_text(result.stdout + result.stderr)
            passed = tap_passed(result.stdout, result.returncode)
            report['cases'][name] = {'status': 'PASS' if passed else 'FAIL', 'returncode': result.returncode,
                                     'tests': len(re.findall(r'^ok \d+\b', result.stdout, re.M))}
        report['status'] = 'PASS' if all(c['status'] == 'PASS' for c in report['cases'].values()) else 'FAIL'
    finally:
        (out / 'results.json').write_text(json.dumps(report, indent=2) + '\n')
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
