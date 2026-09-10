#!/usr/bin/python3
"""Keep the final greenboot command separate from bootupd's closing comment."""
import hashlib
import json
from pathlib import Path
import sys


def repair(data):
    if data.rstrip(b'\n').splitlines()[-1:] != [b'save_env boot_success']:
        raise ValueError('Review the greenboot fragment before changing an unknown final command')
    return data if data.endswith(b'\n') else data + b'\n'


if __name__ == '__main__':
    path = Path(sys.argv[1])
    before = path.read_bytes()
    after = repair(before)
    if before != after:
        path.write_bytes(after)
    print(json.dumps({'path': str(path), 'changed': before != after,
                      'before_sha256': hashlib.sha256(before).hexdigest(),
                      'after_sha256': hashlib.sha256(after).hexdigest(),
                      'recovery_acceptance': 'NOT TESTED'}, indent=2))
