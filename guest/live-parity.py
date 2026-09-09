import json
from pathlib import Path
import sys

PROTECTED = ('kernel', 'kmod', 'akmod', 'nvidia', 'libnvidia', 'xorg-x11-drv-nvidia', 'linux-firmware', 'alsa', 'pipewire', 'wireplumber', 'libfprint', 'fprintd', 'gnome', 'mutter', 'gdm', 'pam', 'mesa')


def compare(target, live):
    before = {x.split()[0]: x for x in target.splitlines()}
    after = {x.split()[0]: x for x in live.splitlines()}
    differences = {name: {'target': before.get(name), 'live': after.get(name)} for name in before.keys() | after.keys() if before.get(name) != after.get(name)}
    forbidden = {name: value for name, value in differences.items() if name.startswith(PROTECTED) or 'firmware' in name}
    return {'status': 'FAIL' if forbidden else 'PASS', 'package_differences': differences, 'protected_differences': forbidden, 'kernel_binary_parity': 'NOT TESTED'}


if __name__ == '__main__':
    result = compare(Path(sys.argv[1]).read_text(), Path(sys.argv[2]).read_text())
    print(json.dumps(result, indent=2))
    raise SystemExit(result['status'] != 'PASS')
