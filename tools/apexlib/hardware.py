"""Read audio and fingerprint observations without changing devices or services."""
from datetime import datetime, timezone
from pathlib import Path
import re
import shutil
import subprocess
import uuid

from .common import atomic_json

LIMIT = 256 * 1024


def read(path):
    try:
        with path.open('rb') as stream:
            data = stream.read(LIMIT + 1)
        return {'status': 'READ', 'text': data[:LIMIT].decode(errors='replace'), 'truncated': len(data) > LIMIT}
    except OSError as exc:
        return {'status': 'UNAVAILABLE', 'error': str(exc)}


def command(args):
    if not shutil.which(args[0]):
        return {'status': 'UNAVAILABLE', 'reason': 'Tool is not installed', 'argv': args}
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=15)
        return {'status': 'READ' if result.returncode == 0 else 'UNAVAILABLE', 'argv': args,
                'returncode': result.returncode, 'stdout': result.stdout[:LIMIT], 'stderr': result.stderr[:LIMIT],
                'truncated': len(result.stdout) > LIMIT or len(result.stderr) > LIMIT}
    except subprocess.TimeoutExpired:
        return {'status': 'UNAVAILABLE', 'reason': 'Read timed out after 15 seconds', 'argv': args}


def collect(directory):
    output = directory / 'hardware-observations' / uuid.uuid4().hex
    output.mkdir(parents=True, mode=0o700)
    report = {'created_at': datetime.now(timezone.utc).isoformat(),
              'scope': 'Read-only observations of the current system, not hardware acceptance',
              'cold_boot_provenance': 'UNKNOWN', 'prior_workaround_state': 'UNKNOWN',
              'audio_acceptance': 'NOT TESTED', 'fingerprint_acceptance': 'NOT TESTED',
              'files': {}, 'commands': {}, 'usb_devices': []}
    paths = [Path(p) for p in ('/etc/os-release', '/proc/sys/kernel/random/boot_id', '/proc/uptime',
                               '/proc/cmdline', '/proc/asound/cards', '/proc/asound/pcm',
                               '/sys/class/dmi/id/sys_vendor', '/sys/class/dmi/id/product_name',
                               '/sys/class/dmi/id/board_name', '/sys/module/snd_hda_intel/parameters/model')]
    paths += sorted(Path('/proc/asound').glob('card[0-9]*/codec#*'))
    # These HDA sysfs files expose configuration, not coefficient-register values.
    # Reading init_verbs does not reveal all built-in kernel fixups.
    for codec in sorted(Path('/sys/class/sound').glob('hwC*D*')):
        paths += [codec / name for name in ('init_pin_configs', 'driver_pin_configs', 'user_pin_configs',
                                          'init_verbs', 'hints', 'modelname', 'subsystem_id',
                                          'vendor_id', 'power/runtime_status')]
    for path in paths:
        report['files'][str(path)] = read(path)
    commands = {
        'kernel': ['uname', '-r'], 'pipewire': ['wpctl', 'status'],
        'fingerprint-unit': ['systemctl', 'show', 'fprintd.service', '-p', 'ActiveState', '-p', 'MainPID',
                             '-p', 'ExecMainStartTimestampMonotonic', '-p', 'NRestarts'],
        # GetNameOwner is served by the bus itself and does not activate fprintd.
        'fingerprint-owner': ['busctl', '--system', 'call', 'org.freedesktop.DBus', '/org/freedesktop/DBus',
                              'org.freedesktop.DBus', 'GetNameOwner', 's', 'net.reactivated.Fprint'],
        'fingerprint-journal': ['journalctl', '-b', '-u', 'fprintd.service', '-n', '400', '-o', 'short-monotonic', '--no-pager'],
        'audio-kernel-journal': ['journalctl', '-b', '-k', '-g', 'snd_hda|hdaudio|ALC294|audio',
                                 '-n', '300', '-o', 'short-monotonic', '--no-pager'],
        'audio-routing': ['pactl', '--format=json', 'list', 'sinks'],
    }
    if shutil.which('rpm') and not shutil.which('dpkg-query'):
        commands['packages'] = ['rpm', '-q', 'kernel-core', 'libfprint', 'fprintd', 'pipewire', 'wireplumber', 'alsa-ucm']
    elif shutil.which('dpkg-query'):
        commands['packages'] = ['dpkg-query', '-W', 'libfprint-2-2', 'fprintd', 'pipewire', 'wireplumber', 'alsa-ucm-conf']
    for card in sorted(Path('/proc/asound').glob('card[0-9]*')):
        if re.fullmatch('card[0-9]+', card.name) and card.is_dir():
            commands[card.name + '-mixer'] = ['amixer', '-c', card.name[4:], 'contents']
    for label, args in commands.items():
        report['commands'][label] = command(args)
    for device in sorted(Path('/sys/bus/usb/devices').glob('*')):
        vendor, product = read(device / 'idVendor'), read(device / 'idProduct')
        if vendor.get('text', '').strip() == '04f3' and product.get('text', '').strip() == '0c6e':
            report['usb_devices'].append({'path': str(device), 'id': '04f3:0c6e',
                                          'product': read(device / 'product'),
                                          'runtime_status': read(device / 'power/runtime_status')})
    # Never read fingerprint templates, claim a sensor, play audio, set controls,
    # invoke hda-verb, restart daemons, change PAM or request elevated host access.
    atomic_json(output / 'observations.json', report)
    return output / 'observations.json'
