"""Evaluate actual boot/journal observations, not simulated recovery state."""
import json

from .common import Blocked


def evaluate_gdm(journal, good, bad):
    events = [json.loads(line) for line in journal.splitlines() if line.strip()]
    observations = []
    messages = {}
    for event in events:
        message = event.get('MESSAGE', '')
        boot_id = event.get('_BOOT_ID', '')
        if not isinstance(message, str):
            continue
        messages.setdefault(boot_id, []).append(message)
        if message.startswith('APEX_RECOVERY_OBSERVATION '):
            data = json.loads(message.removeprefix('APEX_RECOVERY_OBSERVATION '))
            if data['boot_id'].replace('-', '') != boot_id:
                raise Blocked('Observer and journal boot identities differ')
            observations.append(data)
    failed = []
    counters = []
    recovery = None
    for obs in observations:
        if obs['phase'] != 'health-before':
            continue
        boot_id = obs['boot_id']
        if obs['digest'] == bad:
            if recovery or boot_id in failed:
                raise Blocked('Repeated health check or a return to the bad deployment')
            injection = [o for o in observations if o['boot_id'] == boot_id and o['phase'] == 'gdm-start' and o['injected']]
            lines = messages[boot_id.replace('-', '')]
            if len(injection) != 1 or injection[0]['digest'] != bad or 'ActiveState=failed\n' not in obs['gdm']['stdout']:
                raise Blocked('Missing evidence of a real GDM start failure')
            if not any('gdm.service: Control process exited, code=exited, status=42/' in s for s in lines):
                raise Blocked('GDM did not fail with the injected exit status')
            if not any('required script /usr/lib/greenboot/check/required.d/20-apex-system.sh failed!' in s for s in lines):
                raise Blocked('The production Apex health check did not reject the boot')
            env = dict(s.split('=', 1) for s in obs['grubenv']['stdout'].splitlines())
            if env.get('boot_success') != '0' or env.get('greenboot_next_deployment_id') != bad:
                raise Blocked('Missing GRUB failure status or expected rollback identity')
            counters.append(env.get('boot_counter'))
            failed.append(boot_id)
        elif obs['digest'] == good and failed and recovery is None:
            lines = messages[boot_id.replace('-', '')]
            if 'ActiveState=active\n' not in obs['gdm']['stdout'] or not any('greenboot health-check passed.' in s for s in lines):
                raise Blocked('Fallback deployment did not pass its real health check')
            recovery = boot_id
    if not failed or not recovery:
        raise Blocked('Both fault and completed fallback boots are required')
    if not any('Rollback successful' in s for s in messages[failed[-1].replace('-', '')]):
        raise Blocked('No successful greenboot rollback in the final failed boot')
    expected_counters = [None] + [str(n) for n in range(len(failed) - 2, -1, -1)]
    if counters != expected_counters:
        raise Blocked('Unexpected persistent GRUB counter sequence')
    return {'automatic_gdm_fallback': 'PASS',
            'two_failure_limit': 'PASS' if len(failed) == 2 else 'FAIL',
            'failed_boot_ids': failed, 'fallback_boot_id': recovery,
            'counter_before_health': counters, 'good_digest': good, 'bad_digest': bad,
            'scope': 'Instrumented VM fixture; desktop, TTY and data need separate proof'}
