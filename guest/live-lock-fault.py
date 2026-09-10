#!/usr/bin/python3
"""Exercise the unmodified guard with a kernel-denied BLKROSET in initramfs."""
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess

from apex_live_write import require_live_vm, inventory

GUARD = Path('/usr/libexec/apex/live-disk-guard.sh')
CAP_SYS_ADMIN = 21
PR_CAPBSET_DROP = 24


def drop_sys_admin():
    libc = ctypes.CDLL(None, use_errno=True)
    libc.prctl.argtypes = [ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong]
    libc.prctl.restype = ctypes.c_int
    if libc.prctl(PR_CAPBSET_DROP, CAP_SYS_ADMIN, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), 'Cannot restrict the fault child')


def require_initramfs():
    require_live_vm()
    if (not Path('/etc/initrd-release').is_file()
            or any(line.split()[1] == '/sysroot' for line in Path('/proc/mounts').read_text().splitlines())
            or Path('/run/apex-protection-failed').exists()):
        raise RuntimeError('Requires a clean pre-mount initramfs breakpoint')
    expected = globals().get('EXPECTED_GUARD_SHA256', '')
    if not re.fullmatch('[a-f0-9]{64}', expected) or hashlib.sha256(GUARD.read_bytes()).hexdigest() != expected:
        raise RuntimeError('Guard differs from the reviewed source')


def validate_denial(code, error, caps, readonly, latched):
    if (code == 0 or 'Permission denied' not in error
            or caps.keys() != {'CapEff', 'CapBnd'}
            or any(int(value, 16) & (1 << CAP_SYS_ADMIN) for value in caps.values())
            or readonly != '0' or not latched):
        raise RuntimeError('Did not observe the expected kernel permission denial and latch')


def main():
    require_initramfs()
    nodes = inventory()
    target = next(node for node in nodes if node['serial'] == 'apex-other-1')
    device = '/dev/' + target['name']
    ro = Path('/sys/class/block') / target['name'] / 'ro'
    report = {'status': 'FAIL', 'scope': 'Initramfs guard with CAP_SYS_ADMIN removed from child',
              'guard_sha256': hashlib.sha256(GUARD.read_bytes()).hexdigest(),
              'target': target, 'commands': [], 'boot_rejection': 'NOT TESTED',
              'whole_disk_comparison': 'NOT TESTED'}

    def invoke(args, *, check=True, restricted=False):
        result = subprocess.run(args, capture_output=True, text=True, timeout=20,
                                preexec_fn=drop_sys_admin if restricted else None,
                                env=dict(os.environ, LC_ALL='C'))
        report['commands'].append({'argv': args, 'restricted_child': restricted,
                                   'returncode': result.returncode, 'stdout': result.stdout,
                                   'stderr': result.stderr})
        if check and result.returncode:
            raise RuntimeError('Fixture command failed: ' + str(args))
        return result

    invoke(['udevadm', 'settle', '--timeout=15'])
    stopped = False
    try:
        invoke(['udevadm', 'control', '--stop-exec-queue'])
        stopped = True
        invoke(['blockdev', '--setrw', device])
        if ro.read_text().strip() != '0':
            raise RuntimeError('Fixture was not writable before the denied lock')
        report['ro_before_denial'] = '0'
        script = ('sed -n "/^CapEff:/p; /^CapBnd:/p" /proc/self/status; exec '
                  + shlex.quote(str(GUARD)) + ' ' + shlex.quote(device))
        result = invoke(['/bin/sh', '-c', script], check=False, restricted=True)
        caps = dict(re.findall(r'(CapEff|CapBnd):\s*([0-9a-f]+)', result.stdout))
        report['child_capabilities'] = caps
        report['ro_after_denial'] = ro.read_text().strip()
        report['failure_latched'] = Path('/run/apex-protection-failed').is_file()
        validate_denial(result.returncode, result.stderr, caps,
                        report['ro_after_denial'], report['failure_latched'])
        report['kernel_denial'] = 'PASS'
    finally:
        try:
            if stopped:
                invoke(['blockdev', '--setro', device])
                report['ro_after_cleanup'] = ro.read_text().strip()
                if report['ro_after_cleanup'] != '1':
                    raise RuntimeError('Fixture protection was not restored')
        finally:
            if stopped:
                invoke(['udevadm', 'control', '--start-exec-queue'])
            if report.get('kernel_denial') == 'PASS' and report.get('ro_after_cleanup') == '1':
                report['status'] = 'PASS'
            print(json.dumps(report, indent=2), flush=True)


if __name__ == '__main__':
    main()
