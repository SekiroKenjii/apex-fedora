"""Generate credentials for a private QCOW2 fixture, never for an OCI image."""
import json
from pathlib import Path
import secrets
import subprocess

from .common import atomic_json, run


def create(directory: Path) -> Path:
    access = directory / 'test-access'
    access.mkdir(mode=0o700)
    key = access / 'id_ed25519'
    run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-C', 'apex-disposable-test', '-f', key])
    password = secrets.token_urlsafe(24)
    hashed = subprocess.run(['openssl', 'passwd', '-6', '-stdin'], input=password + '\n', text=True, capture_output=True, check=True).stdout.strip()
    atomic_json(access / 'credentials.json', {'user': 'apex-test', 'password': password, 'key': str(key)})
    # These boot arguments apply only to the test disk. The OCI image is unchanged.
    blueprint = access / 'blueprint.toml'
    blueprint.write_text('\n'.join([
        '[[customizations.user]]', 'name = "apex-test"',
        'description = "Disposable Apex VM test account"',
        f'password = {json.dumps(hashed)}',
        f'key = {json.dumps(key.with_suffix(".pub").read_text().strip())}',
        'groups = ["wheel"]', '', '[customizations.kernel]',
        'append = "systemd.wants=sshd.service"', '',
    ]))
    blueprint.chmod(0o600)
    return blueprint
