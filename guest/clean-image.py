#!/usr/bin/python3
"""Remove only known build caches from a disposable image layer."""
import json
from pathlib import Path
import shutil


def main():
    if not Path('/tmp/apex-rpms').is_dir() or not Path('/run/.containerenv').exists():
        raise SystemExit('Image cleanup requires the isolated build container')
    paths = (
        '/run/dnf', '/run/apex-verify-user', '/run/systemd/ask-password', '/run/systemd/systemd-units-load',
        '/var/cache/libdnf5', '/var/lib/dnf/repos',
        '/var/log/dnf5.log', '/var/cache/ldconfig/aux-cache',
    )
    removed = []
    for name in paths:
        path = Path(name)
        if path.is_symlink():
            raise SystemExit(f'Unexpected symlink at build cache path: {name}')
        if path.is_dir():
            shutil.rmtree(path)
            removed.append(name)
        elif path.is_file():
            path.unlink()
            removed.append(name)
    runtime = Path('/run/systemd')
    if runtime.is_dir() and not any(runtime.iterdir()):
        runtime.rmdir()
    Path('/usr/share/apex/build-cache-cleanup.json').write_text(json.dumps(removed, indent=2) + '\n')


if __name__ == '__main__':
    main()
