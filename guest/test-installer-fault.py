#!/usr/bin/python3
"""Reject a damaged payload before Anaconda starts in a fresh offline test VM."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess

CASES = {
    'missing-signature': 'signature',
    'altered-signature': 'signature',
    'wrong-key': 'signature',
    'changed-manifest': 'Bundled manifest digest changed',
    'corrupt-blob': 'Bundled blob checksum mismatch',
    'unexpected-source': 'Unexpected payload source',
}
PAYLOAD = Path('/usr/share/apex/payload')
TRUST = Path('/usr/share/apex/installer-trust')
PREFLIGHT = Path('/run/apex/installer-preflight.json')
FAULT_DIRECTORY = Path('/run/apex-installer-fault')
POLICY = Path('/etc/containers/policy.json')
PREFLIGHT_PROGRAM = Path('/usr/libexec/apex/installer-preflight.py')


def run(args):
    return subprocess.check_output(args, text=True, timeout=5).strip()


def unchanged_start_state():
    if PREFLIGHT.exists() or Path('/tmp/anaconda.log').exists():
        raise RuntimeError('This boot has already entered the installer')
    properties = run(['systemctl', 'show', 'anaconda.service', '-p', 'ActiveState',
                      '-p', 'ExecMainStartTimestampMonotonic'])
    if set(properties.splitlines()) != {'ActiveState=inactive', 'ExecMainStartTimestampMonotonic=0'}:
        raise RuntimeError('Anaconda must never have started during this boot')
    for path in Path('/proc').glob('[0-9]*/comm'):
        try:
            if path.read_text().strip() == 'anaconda':
                raise RuntimeError('Anaconda is already running')
        except FileNotFoundError:
            pass
    return properties


def guard(case):
    if case not in CASES or os.geteuid() != 0:
        raise RuntimeError('Choose a named fault in an existing root test session')
    if run(['systemd-detect-virt', '--vm']) not in {'kvm', 'qemu'}:
        raise RuntimeError('Fault injection is restricted to a QEMU test VM')
    cmdline = Path('/proc/cmdline').read_text().strip()
    if 'systemd.unit=multi-user.target' not in cmdline.split():
        raise RuntimeError('Boot the installer into its diagnostic multi-user target first')
    if run(['getenforce']) != 'Enforcing':
        raise RuntimeError('SELinux must remain enforcing')
    if set(p.name for p in Path('/sys/class/net').iterdir()) != {'lo'}:
        raise RuntimeError('The negative installer test must have no network interface')
    for path in (PAYLOAD, TRUST, Path('/usr/share/apex/installer-payload.json')):
        if not path.exists() or path.resolve() != path:
            raise RuntimeError('Expected the Apex live installer payload without symlinks')
    disks = json.loads(run(['lsblk', '-bJ', '-o', 'NAME,SIZE,TYPE,SERIAL,MOUNTPOINTS']))['blockdevices']
    physical = [d for d in disks if d['type'] == 'disk' and not d['name'].startswith('zram')]
    if len(physical) != 2 or sorted(d['size'] for d in physical) != [4 * 1024**3, 48 * 1024**3]:
        raise RuntimeError('Expected only the disposable 48 GiB target and 4 GiB sentinel disk')
    for disk in physical:
        if not re.fullmatch('vd[a-z]', disk['name']):
            raise RuntimeError('Expected virtio test disks only')
        if disk['size'] == 4 * 1024**3 and disk['serial'] != 'apex-other-1':
            raise RuntimeError('Unexpected sentinel disk identity')
        if any(any(p.get('mountpoints', [])) for p in [disk, *disk.get('children', [])]):
            raise RuntimeError('Test disks must be unmounted before fault injection')
    return {'cmdline': cmdline, 'anaconda': unchanged_start_state(), 'disks': disks,
            'selinux': 'Enforcing', 'network': 'loopback-only'}


def mutate(case, wrong_key):
    directory = FAULT_DIRECTORY
    directory.mkdir(mode=0o700)  # One mutation per boot; preserve earlier evidence.
    manifest = json.loads((PAYLOAD / 'manifest.json').read_text())
    if not re.fullmatch('sha256:[a-f0-9]{64}', manifest.get('config', {}).get('digest', '')):
        raise RuntimeError('Expected the frozen config blob digest before injecting a fault')
    target = {'missing-signature': PAYLOAD / 'signature-1',
              'altered-signature': PAYLOAD / 'signature-1',
              'wrong-key': TRUST / 'payload.pub',
              'changed-manifest': PAYLOAD / 'manifest.json',
              'corrupt-blob': PAYLOAD / manifest['config']['digest'].removeprefix('sha256:'),
              'unexpected-source': TRUST / 'payload.json'}[case]
    if target.resolve() != target or not target.is_file():
        raise RuntimeError('Fault target must be a regular file without symlinks')
    original = target.read_bytes()
    (directory / 'original').write_bytes(original)
    if case == 'missing-signature':
        if sorted(p.name for p in PAYLOAD.glob('signature-*')) != ['signature-1']:
            raise RuntimeError('Review an installer with multiple signatures before testing')
        # /run is a different filesystem. The byte-for-byte backup above stays
        # available for inspection after removing this disposable live copy.
        target.unlink()
    elif case in {'altered-signature', 'corrupt-blob'}:
        if not original:
            raise RuntimeError('Cannot mutate an empty fixture')
        target.write_bytes(original[:-1] + bytes([original[-1] ^ 1]))
    elif case == 'changed-manifest':
        # Valid JSON, unchanged descriptors, different signed manifest digest.
        target.write_bytes(original + b'\n')
    elif case == 'unexpected-source':
        value = json.loads(original)
        value['reference'] = 'localhost/apex-untrusted@' + value['digest']
        target.write_text(json.dumps(value))
    elif case == 'wrong-key':
        if not wrong_key.startswith('-----BEGIN PUBLIC KEY-----\n') or wrong_key.encode() == original:
            raise RuntimeError('Supply a different valid public verification key')
        target.write_text(wrong_key)
        metadata_path = TRUST / 'payload.json'
        metadata = json.loads(metadata_path.read_text())
        metadata['public_key_sha256'] = hashlib.sha256(wrong_key.encode()).hexdigest()
        metadata_path.write_text(json.dumps(metadata))
        spec = importlib.util.spec_from_file_location('preflight', PREFLIGHT_PROGRAM)
        preflight = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(preflight)
        policy = preflight.signature_policy(metadata, wrong_key.encode())
        POLICY.write_text(json.dumps(policy))
        # A consistent contract with a different public key reaches the actual
        # signature verifier, not merely the public-key checksum check.
    return {'target': str(target), 'before_sha256': hashlib.sha256(original).hexdigest(),
            'after_sha256': hashlib.sha256(target.read_bytes()).hexdigest() if target.exists() else None}


def main(case, wrong_key=''):
    report = {'case': case, 'status': 'FAIL', 'scope': 'offline installer entry point in a disposable VM'}
    report['before'] = guard(case)
    report['trusted_metadata'] = json.loads((TRUST / 'payload.json').read_text())
    report['mutation'] = mutate(case, wrong_key)
    try:
        result = subprocess.run(['/usr/bin/anaconda', '--text'], capture_output=True, text=True, timeout=35)
        report['returncode'] = result.returncode
        report['stdout'] = result.stdout
        report['stderr'] = result.stderr
        report['preflight'] = json.loads(PREFLIGHT.read_text()) if PREFLIGHT.is_file() else None
        report['upstream_log_created'] = Path('/tmp/anaconda.log').exists()
        report['selinux_after'] = run(['getenforce'])
        error = (report['preflight'] or {}).get('error', '')
        if (result.returncode != 1 or (report['preflight'] or {}).get('status') != 'FAIL'
                or not re.search(CASES[case], error, re.IGNORECASE)
                or report['upstream_log_created'] or report['selinux_after'] != 'Enforcing'):
            raise RuntimeError('The production entry point did not reject the expected fault before Anaconda')
        report['status'] = 'PASS'
    finally:
        print('\nAPEXFAULT:' + json.dumps(report, separators=(',', ':')), flush=True)
    # The host must still power off and compare both whole disks with their
    # pristine sources. This guest report alone does not pass the release gate.


if __name__ == '__main__':
    main(APEX_FAULT, globals().get('APEX_WRONG_PUBLIC_KEY', ''))
