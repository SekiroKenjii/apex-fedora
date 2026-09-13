import json
import stat
import tomllib
from apexlib.testaccess import create


def test_account_is_private_and_blueprint_uses_hash(tmp_path):
    blueprint = create(tmp_path)
    config = tomllib.loads(blueprint.read_text())['customizations']
    credentials = json.loads((blueprint.parent / 'credentials.json').read_text())
    assert credentials['password'] not in blueprint.read_text()
    assert config['user'][0]['password'].startswith('$6$')
    assert config['user'][0]['key'].startswith('ssh-ed25519 ')
    assert 'systemd.wants=sshd.service' in config['kernel']['append']
    assert stat.S_IMODE((blueprint.parent / 'credentials.json').stat().st_mode) == 0o600
    assert stat.S_IMODE(blueprint.stat().st_mode) == 0o600


