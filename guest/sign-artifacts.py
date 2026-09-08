#!/usr/bin/python3
import hashlib
import json
from pathlib import Path
import subprocess
import sys


def main():
    if Path('/etc/apex-builder').read_text().strip() != 'apex-isolated-builder-v1':
        raise SystemExit('Signing is restricted to the builder VM')
    output = Path(sys.argv[1]).resolve()
    target = json.loads(Path(sys.argv[2]).read_text())
    keydir = Path('/var/lib/apex/signing')
    keydir.mkdir(parents=True, exist_ok=True, mode=0o700)
    key = keydir / 'local-dev.key'
    if not key.exists():
        subprocess.run(['openssl', 'genpkey', '-algorithm', 'ED25519', '-out', str(key)], check=True)
        key.chmod(0o600)
    files = {}
    excluded = {'artifacts.json', 'artifacts.sig', 'development-signing.pub'}
    for path in sorted(output.rglob('*')):
        if path.is_symlink():
            raise SystemExit('Cannot sign symbolic links')
        if path.is_file() and path.name not in excluded:
            with path.open('rb') as f:
                files[str(path.relative_to(output))] = hashlib.file_digest(f, 'sha256').hexdigest()
    manifest = output / 'artifacts.json'
    manifest.write_text(json.dumps({'schema': 1, 'purpose': 'development-only', 'digest': target['digest'], 'files': files}, sort_keys=True, indent=2) + '\n')
    subprocess.run(['openssl', 'pkey', '-in', str(key), '-pubout', '-out', str(output / 'development-signing.pub')], check=True)
    subprocess.run(['openssl', 'pkeyutl', '-sign', '-rawin', '-inkey', str(key), '-in', str(manifest), '-out', str(output / 'artifacts.sig')], check=True)


if __name__ == '__main__':
    main()
