#!/usr/bin/python3
"""Adapt the pinned Titanoboa script without flattening image file ownership."""
import hashlib
import json
from pathlib import Path
import sys

UPSTREAM_SHA256 = 'a73e0a11731880bc6272650371427564aaf565d5dc0d9e51dd793d79b351dcba'


def adapt(source):
    if hashlib.sha256(source).hexdigest() != UPSTREAM_SHA256:
        raise ValueError('Review the pinned Titanoboa script before adapting a different source')
    old = b'mksquashfs /rootfs /work/iso-root/LiveOS/squashfs.img -all-root -noappend'
    if source.count(old) != 1:
        raise ValueError('Expected one known squashfs command')
    # Invoking /bin/bash explicitly bypasses the options in the upstream shebang.
    first, separator, rest = source.partition(b'\n')
    source = first + separator + b'set -e -o pipefail\n' + rest
    result = source.replace(old, (
        b'bash /apex-guest/assemble-live-squashfs.sh'))
    result += (b'\n# Retain numeric ownership and mode evidence from the produced filesystem.\n'
               b'unsquashfs -lln /work/iso-root/LiveOS/squashfs.img > /output/squashfs-metadata.txt\n')
    return result


if __name__ == '__main__':
    script = Path(sys.argv[1])
    report = Path(sys.argv[2])
    original = script.read_bytes()
    result = adapt(original)
    script.write_bytes(result)
    report.write_text(json.dumps({'upstream_sha256': hashlib.sha256(original).hexdigest(),
                                  'adapted_sha256': hashlib.sha256(result).hexdigest(),
                                  'changes': ['Preserve source UID/GID instead of forcing all files to root',
                                              'Stop on failed preparation or assembly commands',
                                              'Copy to a VM scratch tree and apply the target SELinux policy',
                                              'Read raw target labels in install_t during squashfs assembly',
                                              'Verify extracted critical-file labels, ownership and content',
                                              'Limit squashfs workers to four and memory to 1 GiB',
                                              'Export numeric squashfs ownership/mode listing'],
                                  'boot_acceptance': 'NOT TESTED'}, indent=2) + '\n')
