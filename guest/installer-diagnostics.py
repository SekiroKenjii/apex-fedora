#!/usr/bin/python3
"""Export installer VM logs to stdout before Anaconda cancellation reboots it."""
import base64
from contextlib import nullcontext
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys

LIMIT = 2 * 1024 * 1024


def read_log(path):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                return {'error': 'not a regular file'}
            data = stream.read(LIMIT + 1)
        return {'data': base64.b64encode(data[:LIMIT]).decode(),
                'sha256': hashlib.sha256(data[:LIMIT]).hexdigest(),
                'truncated': len(data) > LIMIT}
    except OSError as exc:
        return {'error': exc.strerror}


def main(token, serial=False):
    if not re.fullmatch('[a-f0-9]{32}', token):
        raise RuntimeError('Invalid capture token')
    marker = Path('/usr/share/apex/installer-payload.json')
    if os.geteuid() != 0 or not marker.is_file():
        raise RuntimeError('Run from the Apex installer VM rescue login')
    virt = subprocess.run(['systemd-detect-virt', '--vm'], capture_output=True, text=True, timeout=5)
    if virt.returncode or virt.stdout.strip() not in {'kvm', 'qemu'}:
        raise RuntimeError('This collector is restricted to QEMU installer tests')
    commands = {
        'selinux': ['getenforce'],
        'units': ['systemctl', 'show', 'anaconda.service', 'anaconda-pre.service',
                  '-p', 'ActiveState', '-p', 'Result', '-p', 'ExecMainStatus'],
        'journal': ['journalctl', '-b', '-n', '1000', '--no-pager', '-o', 'short-monotonic'],
        'disks': ['lsblk', '--json', '--bytes', '-o', 'NAME,SIZE,TYPE,RO,SERIAL,MOUNTPOINTS'],
    }
    observations = {}
    for name, args in commands.items():
        try:
            result = subprocess.run(args, capture_output=True, timeout=15)
            observations[name] = {'returncode': result.returncode,
                                  'stdout': result.stdout[:LIMIT].decode(errors='replace'),
                                  'stderr': result.stderr[:4096].decode(errors='replace'),
                                  'truncated': len(result.stdout) > LIMIT or len(result.stderr) > 4096}
        except (OSError, subprocess.TimeoutExpired) as exc:
            observations[name] = {'error': type(exc).__name__}
    bundle = {'schema': 1, 'token': token, 'payload': json.loads(marker.read_text()),
              'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
              'logs': {name: read_log('/tmp/' + name) for name in
                       ('anaconda.log', 'storage.log', 'program.log')},
              'observations': observations}
    raw = json.dumps(bundle, separators=(',', ':')).encode()
    encoded = base64.b64encode(raw).decode()
    # Frame every chunk so unrelated kernel messages cannot silently alter the bundle.
    chunks = [encoded[n:n + 768] for n in range(0, len(encoded), 768)]
    if serial:
        # Open the guest port only after the installer and virtualization guards.
        fd = os.open('/dev/ttyS0', os.O_WRONLY | os.O_NOFOLLOW | os.O_NOCTTY)
        if not stat.S_ISCHR(os.fstat(fd).st_mode):
            os.close(fd)
            raise RuntimeError('The guest serial port is not a character device')
        destination = os.fdopen(fd, 'w')
    else:
        destination = nullcontext(sys.stdout)
    with destination as stream:
        print(file=stream)
        for index, chunk in enumerate(chunks):
            print(f'APEXLOG:{token}:{index}:{chunk}', file=stream, flush=True)
        print(f'APEXEND:{token}:{len(chunks)}:{hashlib.sha256(raw).hexdigest()}', file=stream, flush=True)


if __name__ == '__main__':
    try:
        if len(sys.argv) not in {2, 3} or (len(sys.argv) == 3 and sys.argv[2] != '--serial'):
            raise RuntimeError('Usage: installer-diagnostics.py TOKEN [--serial]')
        main(sys.argv[1], serial=len(sys.argv) == 3)
    except (RuntimeError, OSError, ValueError) as exc:
        sys.exit(str(exc))
