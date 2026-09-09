import base64
import importlib.util
from pathlib import Path

import pytest


def fixture_module():
    path = Path(__file__).resolve().parents[1] / 'guest/update-fixture.py'
    spec = importlib.util.spec_from_file_location('update_fixture', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_update_policy_rejects_unknown_paths_and_transports():
    module = fixture_module()
    result = module.policy(b'fixture public key', 'a' * 32)
    assert result['default'] == [{'type': 'reject'}]
    assert set(result['transports']) == {'dir'}
    paths = result['transports']['dir']
    assert {Path(p).name for p in paths} == {'a', 'b', 'wrong-key', 'unsigned'}
    for path, rules in paths.items():
        assert path.startswith('/var/lib/apex-update-fixture/' + 'a' * 32 + '/')
        assert len(rules) == 1
        assert rules[0]['type'] == 'sigstoreSigned'
        assert base64.b64decode(rules[0]['keyData']) == b'fixture public key'
        identity = rules[0]['signedIdentity']
        assert identity['type'] == 'exactReference'
        assert identity['dockerReference'].endswith(':a' if Path(path).name == 'a' else ':b')


@pytest.mark.parametrize('value', ['', '../a', 'A' * 32, 'a' * 31, 'a' * 33, 'a' * 32 + '\n'])
def test_update_policy_refuses_invalid_fixture_identity(value):
    with pytest.raises(ValueError):
        fixture_module().policy(b'public', value)


def runner_module():
    path = Path(__file__).resolve().parents[1] / 'tools/update-vm.py'
    spec = importlib.util.spec_from_file_location('update_vm', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('case,code,error,changed', [
    ('wrong-key', 0, 'signature', False), ('unsigned', 255, 'Connection refused', False),
    ('wrong-key', 1, 'signature failure', True), ('untrusted', 1, 'Image not found', False),
])
def test_rejection_requires_policy_error_and_unchanged_deployments(case, code, error, changed):
    from apexlib.common import Blocked
    with pytest.raises(Blocked):
        runner_module().require_rejection(case, code, error, {}, {'staged': 'new'} if changed else {})


@pytest.mark.parametrize('case,error', [('wrong-key', 'Invalid signature'),
                                      ('unsigned', 'No signatures'), ('untrusted', 'rejected by policy')])
def test_expected_consumer_rejections(case, error):
    runner_module().require_rejection(case, 1, error, {'booted': 'a'}, {'booted': 'a'})
