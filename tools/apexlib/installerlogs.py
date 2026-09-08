"""Private, bounded serial log transfer without a guest NIC or shared filesystem."""
import base64
import binascii
import hashlib
import json
from pathlib import Path
import re
import uuid

from .common import Blocked, atomic_json, regular_file, sha256
from .vm import alive

MAX_BYTES = 16 * 1024 * 1024


def valid_token(token):
    if not re.fullmatch('[a-f0-9]{32}', token):
        raise Blocked('Invalid installer capture token')


def decode(lines, token):
    valid_token(token)
    chunks, end, size = {}, None, 0
    prefix, suffix = f'APEXLOG:{token}:', f'APEXEND:{token}:'
    for raw_line in lines:
        line = raw_line.decode('ascii', errors='replace').strip('\r\n')
        if not line.startswith((prefix, suffix)):
            continue
        fields = line.split(':')
        if len(fields) != 4 or not re.fullmatch('[0-9]{1,6}', fields[2]):
            raise Blocked('Malformed installer log frame')
        index = int(fields[2])
        if line.startswith(prefix):
            if index != len(chunks) or end is not None or not re.fullmatch('[A-Za-z0-9+/=]{1,768}', fields[3]):
                raise Blocked('Duplicate or malformed installer log chunk')
            size += len(fields[3])
            if size > MAX_BYTES:
                raise Blocked('Installer log bundle exceeds the transfer limit')
            chunks[index] = fields[3]
        else:
            if end is not None or not re.fullmatch('[a-f0-9]{64}', fields[3]):
                raise Blocked('Duplicate or malformed installer log trailer')
            end = (index, fields[3])
    if end is None or end[0] == 0 or len(chunks) != end[0] or any(n not in chunks for n in range(end[0])):
        raise Blocked('Installer logs are incomplete; do not cancel the installer yet')
    try:
        data = base64.b64decode(''.join(chunks[n] for n in range(end[0])), validate=True)
        if hashlib.sha256(data).hexdigest() != end[1]:
            raise Blocked('Installer log checksum mismatch')
        bundle = json.loads(data)
    except (ValueError, binascii.Error) as exc:
        raise Blocked('Invalid installer log payload') from exc
    if not isinstance(bundle, dict) or bundle.get('schema') != 1 or bundle.get('token') != token:
        raise Blocked('Installer log bundle does not match its request')
    return bundle


def prepare(directory: Path):
    info = alive(directory)
    if not info or info['role'] != 'test' or not info.get('iso'):
        raise Blocked('Log capture requires an owned installer test VM')
    run = Path(info['artifacts_dir'])
    regular_file(run / 'vm.json', within=directory / 'vm-runs')
    iso = regular_file(Path(info['iso']), within=directory)
    token = uuid.uuid4().hex
    target = run / 'installer-logs' / token
    request = {'token': token, 'vm': info, 'iso_sha256': sha256(iso)}
    if alive(directory) != info:
        raise Blocked('Installer VM changed while preparing log capture')
    atomic_json(target / 'request.json', request)
    return {'token': token, 'run_directory': str(run),
            'guest_command': f'python3 /usr/libexec/apex/installer-diagnostics.py {token} --serial',
            'instruction': 'Run the guest command from the installer rescue login; then collect before confirming cancellation.'}


def collect(directory: Path, run: Path, token: str):
    valid_token(token)
    regular_file(run / 'vm.json', within=directory / 'vm-runs')
    target = run / 'installer-logs' / token
    request = json.loads(regular_file(target / 'request.json', within=run).read_text())
    if request.get('token') != token or Path(request['vm']['artifacts_dir']).resolve() != run.resolve():
        raise Blocked('Installer capture request belongs to another test')
    serial = regular_file(run / 'test-serial.log', within=run)
    with serial.open('rb') as stream:
        # A corrupted serial file must not force an unbounded line allocation.
        def lines():
            while line := stream.readline(16384):
                if len(line) == 16384 and not line.endswith(b'\n'):
                    raise Blocked('Oversized serial line; retain the raw log for review')
                yield line
        bundle = decode(lines(), token)
    saved = target / 'bundle.json'
    if saved.exists():
        raise Blocked('Capture already exists; prepare a new token instead of overwriting it')
    atomic_json(saved, bundle)
    logs = bundle.get('logs', {})
    complete = isinstance(logs, dict)
    for name in ('anaconda.log', 'storage.log', 'program.log'):
        item = logs.get(name, {}) if isinstance(logs, dict) else {}
        try:
            data = base64.b64decode(item['data'], validate=True)
            complete &= item.get('truncated') is False and 'error' not in item and hashlib.sha256(data).hexdigest() == item['sha256']
        except (KeyError, TypeError, ValueError, binascii.Error):
            complete = False
    report = {'transport': 'PASS', 'required_logs_complete': complete,
              'bundle_sha256': sha256(saved), 'iso_sha256': request['iso_sha256'],
              'acceptance': 'NOT TESTED', 'bundle': str(saved)}
    atomic_json(target / 'result.json', report)
    return report
