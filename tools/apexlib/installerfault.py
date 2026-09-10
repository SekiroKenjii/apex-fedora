"""Run one pre-partition fault, then collect whole-disk evidence after shutdown."""
import json
from pathlib import Path
import re

from .common import ROOT, Blocked, atomic_json, regular_file, sha256
from .serialconsole import SerialConsole
from . import vm

CASES = ('missing-signature', 'altered-signature', 'wrong-key', 'changed-manifest',
         'corrupt-blob', 'unexpected-source')


def parse(response, case):
    matches = re.findall(rb'(?:^|\n)APEXFAULT:(\{[^\r\n]+\})(?=\r?\n)', response)
    if len(matches) != 1:
        raise Blocked('Expected exactly one complete guest fault report')
    result = json.loads(matches[0])
    if (result.get('case') != case or result.get('status') != 'PASS'
            or result.get('returncode') != 1 or result.get('preflight', {}).get('status') != 'FAIL'
            or result.get('upstream_log_created') is not False or result.get('selinux_after') != 'Enforcing'):
        raise Blocked('Guest did not confirm the expected pre-Anaconda rejection')
    return result


def execute(directory, case, wrong_key=None):
    if case not in CASES or (case == 'wrong-key') != (wrong_key is not None):
        raise Blocked('Choose a known case; only wrong-key requires a public key fixture')
    info = vm.alive(directory)
    if (not info or info['role'] != 'test' or not info.get('iso') or info.get('guest_ssh')
            or not info.get('serial_console') or len(info.get('extra_disks', [])) != 1):
        raise Blocked('Use a fresh offline serial-enabled installer VM with one extra disk')
    run = Path(info['artifacts_dir'])
    request = run / 'fault-request.json'
    if request.exists():
        raise Blocked('Use a fresh VM for every fault, including retries after a setup failure')
    iso = regular_file(Path(info['iso']), within=directory)
    source = f'APEX_FAULT = {case!r}\n'
    if wrong_key is not None:
        key = regular_file(wrong_key, within=directory)
        if key.stat().st_size > 4096 or not key.read_text().startswith('-----BEGIN PUBLIC KEY-----\n'):
            raise Blocked('Supply only a small public verification key, never a private key')
        source += f'APEX_WRONG_PUBLIC_KEY = {key.read_text()!r}\n'
    source += (ROOT / 'guest/test-installer-fault.py').read_text()
    atomic_json(request, {'case': case, 'iso_sha256': sha256(iso), 'vm_pid': info['pid']})
    console = SerialConsole(directory)
    try:
        capture, response = console.execute(source)
    finally:
        console.close()
    result = parse(response, case)
    atomic_json(run / 'fault-guest.json', {'capture': str(capture), 'guest': result})
    return {'case': case, 'entrypoint_rejected': True, 'run_directory': str(run),
            'disk_preservation': 'NOT TESTED', 'next': 'Power off this test VM, then collect disk comparisons'}


def collect(directory, run):
    if vm.alive(directory):
        raise Blocked('Power off the test VM before collecting whole-disk comparisons')
    request = json.loads(regular_file(run / 'fault-request.json', within=directory / 'vm-runs').read_text())
    saved = json.loads(regular_file(run / 'vm.json', within=directory / 'vm-runs').read_text())
    guest = json.loads(regular_file(run / 'fault-guest.json', within=directory / 'vm-runs').read_text())
    # Revalidate the report rather than trusting a status string alone.
    parse(('APEXFAULT:' + json.dumps(guest['guest']) + '\n').encode(), request['case'])
    iso = regular_file(Path(saved['iso']), within=directory)
    if sha256(iso) != request['iso_sha256']:
        raise Blocked('The source ISO changed during the test')
    comparison = vm.compare_disks(directory, run)
    passed = len(comparison['disks']) == 2 and all(d['unchanged'] for d in comparison['disks'])
    result = {'status': 'PASS' if passed else 'FAIL', 'case': request['case'],
              'iso_sha256': request['iso_sha256'], 'guest': guest,
              'disk_comparison': comparison, 'run_directory': str(run)}
    atomic_json(run / 'fault-result.json', result)
    if not passed:
        raise Blocked('A virtual disk changed during payload rejection; inspect fault-result.json')
    return {'status': result['status'], 'case': result['case'], 'proof': str(run / 'fault-result.json')}
