import importlib.util

from apexlib.common import ROOT

spec = importlib.util.spec_from_file_location('recovery_probe', ROOT / 'guest/recovery-probe.py')
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def image(character):
    return {'image': {'imageDigest': 'sha256:' + character*64}}


def test_first_install_has_no_fallback():
    result = probe.prerequisites({'status': {'booted': image('a'), 'rollback': None}})
    assert result['status'] == 'BLOCKED'
    assert result['reasons'] == ['No rollback image digest']


def test_identical_deployments_do_not_exercise_an_update():
    assert probe.prerequisites({'status': {'booted': image('a'), 'rollback': image('a')}})['status'] == 'BLOCKED'


def test_two_images_do_not_prove_recovery():
    assert probe.prerequisites({'status': {'booted': image('b'), 'rollback': image('a')}})['status'] == 'NOT TESTED'
