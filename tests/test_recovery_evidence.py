import copy
import json

import pytest

from apexlib.common import Blocked
from apexlib.recovery import evaluate_gdm


def journal(failures):
    events = []
    for n in range(failures + 1):
        failed = n < failures
        identity = str(n + 1) * 32
        env = 'boot_success=0\ngreenboot_next_deployment_id=bad\n'
        if n:
            env += f'boot_counter={failures - n - 1}\n'
        obs = {'boot_id': identity, 'phase': 'gdm-start', 'digest': 'bad' if failed else 'good',
               'injected': failed, 'gdm': {'stdout': 'ActiveState=failed\n' if failed else 'ActiveState=active\n'},
               'grubenv': {'stdout': env}}
        for phase in ['gdm-start', 'health-before']:
            row = copy.deepcopy(obs)
            row['phase'] = phase
            events.append({'_BOOT_ID': identity, 'MESSAGE': 'APEX_RECOVERY_OBSERVATION ' + json.dumps(row)})
        message = 'required script /usr/lib/greenboot/check/required.d/20-apex-system.sh failed!' if failed else 'greenboot health-check passed.'
        events.append({'_BOOT_ID': identity, 'MESSAGE': message})
        if failed:
            events.append({'_BOOT_ID': identity, 'MESSAGE': 'gdm.service: Control process exited, code=exited, status=42/n/a'})
        if n == failures - 1:
            events.append({'_BOOT_ID': identity, 'MESSAGE': 'Rollback successful'})
    return '\n'.join(json.dumps(e) for e in events)


def test_three_actual_failures_do_not_pass_the_two_failure_requirement():
    result = evaluate_gdm(journal(3), 'good', 'bad')
    assert result['automatic_gdm_fallback'] == 'PASS'
    assert result['two_failure_limit'] == 'FAIL'
    assert result['counter_before_health'] == [None, '1', '0']


def test_two_observed_failures_and_healthy_fallback():
    result = evaluate_gdm(journal(2), 'good', 'bad')
    assert result['two_failure_limit'] == 'PASS'
    assert len(result['failed_boot_ids']) == 2


@pytest.mark.parametrize('old,new', [
    ('Rollback successful', 'Rollback failed'),
    ('ActiveState=failed', 'ActiveState=inactive'),
    ('greenboot health-check passed.', 'greenboot error'),
    ('greenboot_next_deployment_id=bad', 'greenboot_next_deployment_id=unknown'),
    ('boot_counter=0', 'boot_counter=9'),
    ('gdm-start', 'unknown'),
    ('status=42/', 'status=13/'),
])
def test_missing_or_contradictory_proof_blocks_acceptance(old, new):
    with pytest.raises(Blocked):
        evaluate_gdm(journal(2).replace(old, new), 'good', 'bad')
