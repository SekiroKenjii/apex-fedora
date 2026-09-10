#!/usr/bin/python3
"""Per-process render offload and passive PCI runtime-power observations."""
import argparse
import json
import os
from pathlib import Path
import sys

OFFLOAD = {'__NV_PRIME_RENDER_OFFLOAD': '1', '__GLX_VENDOR_LIBRARY_NAME': 'nvidia',
           '__VK_LAYER_NV_optimus': 'NVIDIA_only'}


def read(path):
    try:
        return path.read_text().strip()
    except OSError:
        return None


def inventory(pci=Path('/sys/bus/pci/devices')):
    devices = []
    for device in sorted(pci.iterdir()):
        vendor, device_class = read(device / 'vendor'), read(device / 'class')
        if vendor not in {'0x10de', '0x1002'} or not device_class or not device_class.startswith('0x03'):
            continue
        driver = device / 'driver'
        devices.append({'pci': device.name, 'vendor': vendor, 'device': read(device / 'device'),
                        'driver': driver.resolve().name if driver.is_symlink() else None,
                        'runtime_status': read(device / 'power/runtime_status'),
                        'power_control': read(device / 'power/control'),
                        'runtime_suspended_time_ms': read(device / 'power/runtime_suspended_time'),
                        'runtime_active_time_ms': read(device / 'power/runtime_active_time')})
    return devices


def launch_environment(devices, environ):
    nvidia = [d for d in devices if d['vendor'] == '0x10de' and d['driver'] == 'nvidia']
    if len(nvidia) != 1:
        raise ValueError('Render offload requires exactly one NVIDIA display device bound to nvidia')
    return {**environ, **OFFLOAD}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    sub.add_parser('status')
    launch = sub.add_parser('run')
    launch.add_argument('--gpu', choices=['nvidia'], required=True)
    launch.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    devices = inventory()
    if args.action == 'status':
        print(json.dumps({'devices': devices, 'method': 'passive-sysfs',
                          'render_offload': 'NOT TESTED', 'hardware_acceptance': 'NOT TESTED'}, indent=2))
        return
    command = args.command
    if command[:1] == ['--']:
        command = command[1:]
    if not command:
        parser.error('A command is required after --')
    if os.geteuid() == 0:
        parser.error('Run desktop applications as your normal user')
    try:
        environment = launch_environment(devices, os.environ)
        os.execvpe(command[0], command, environment)
    except (ValueError, OSError) as error:
        parser.exit(2, str(error) + '\n')


if __name__ == '__main__':
    main()
