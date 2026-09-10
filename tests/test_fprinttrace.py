import copy
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from apexlib.common import ROOT
from apexlib.fprinttrace import Trace, INTERFACE, SERVICE, MATCHES, parse_line

DEVICE = '/net/reactivated/Fprint/Device/0'


def call(method='Claim', client=':1.2', serial=2, destination=SERVICE):
    return {'type': 'method_call', 'cookie': serial, 'timestamp-realtime': 100,
            'sender': client, 'destination': destination, 'path': DEVICE,
            'interface': INTERFACE, 'member': method,
            'payload': {'type': 's', 'data': ['PRIVATE USERNAME']}}


def reply(client=':1.2', serial=2, error=None):
    return {'type': 'error' if error else 'method_return', 'reply_cookie': serial,
            'timestamp-realtime': 101, 'sender': ':1.10', 'destination': client,
            'error_name': error, 'payload': {'type': 's', 'data': ['PRIVATE ERROR BODY']}}


def disconnect(client=':1.2'):
    return {'type': 'signal', 'timestamp-realtime': 102, 'sender': 'org.freedesktop.DBus',
            'interface': 'org.freedesktop.DBus', 'member': 'NameOwnerChanged',
            'payload': {'type': 'sss', 'data': [client, client, '']}}


def status():
    return {'type': 'signal', 'timestamp-realtime': 103, 'sender': ':1.10', 'path': DEVICE,
            'interface': INTERFACE, 'member': 'EnrollStatus',
            'payload': {'type': 'sb', 'data': ['enroll-disconnected', True]}}


def test_error_event_does_not_implicitly_release_claim():
    trace = Trace()
    for message in (call(), reply(), status()):
        trace.feed(message)
    assert trace.owners[DEVICE] == ':1.2'
    assert trace.summary()['fingerprint_acceptance'] == 'NOT TESTED'
    assert trace.summary()['successful_releases'] == 0


def test_second_client_denied_until_observed_release():
    trace = Trace()
    for message in (call(), reply(), call(client=':1.3'),
                    reply(client=':1.3', error=SERVICE + '.Error.AlreadyInUse'),
                    call('Release', serial=3), reply(serial=3), call(client=':1.3', serial=4),
                    reply(client=':1.3', serial=4)):
        trace.feed(message)
    assert trace.owners[DEVICE] == ':1.3'
    assert trace.summary()['claim_denials'] == trace.summary()['successful_releases'] == 1
    denial = next(e for e in trace.events if e.get('outcome') == 'ERROR')
    assert denial['last_observed_owner'] == ':1.2' and denial['caller_was_last_owner'] is False


def test_same_client_reclaim_is_distinguishable_from_other_process():
    trace = Trace()
    for message in (call(), reply(), call(serial=3), reply(serial=3, error=SERVICE + '.Error.AlreadyInUse')):
        trace.feed(message)
    assert trace.events[-1]['caller_was_last_owner'] is True


def test_disappearance_needs_later_success_to_confirm_reacquisition():
    trace = Trace()
    for message in (call(), reply(), disconnect()):
        trace.feed(message)
    assert trace.owners[DEVICE] == ':1.2'
    assert trace.summary()['claims_after_disconnect'] == 0
    trace.feed(call(client=':1.3'))
    trace.feed(reply(client=':1.3'))
    assert trace.summary()['claims_after_disconnect'] == 1


def test_serial_is_scoped_to_client_and_reply_destination():
    trace = Trace()
    trace.feed(call())
    trace.feed(call(client=':1.3'))
    trace.feed(reply(client=':1.3', error=SERVICE + '.Error.AlreadyInUse'))
    assert (':1.2', 2) in trace.pending
    assert trace.owners == {}
    trace.feed(reply())
    assert trace.owners[DEVICE] == ':1.2'


def test_unknown_initial_owner_and_incomplete_trace_are_explicit():
    trace = Trace()
    trace.feed(call())
    trace.feed(reply(error=SERVICE + '.Error.AlreadyInUse'))
    assert trace.events[-1]['last_observed_owner'] == 'UNKNOWN'
    assert trace.events[-1]['caller_was_last_owner'] is None
    trace.feed(call('EnrollStart', serial=3))
    assert trace.summary()['capture_status'] == 'INCOMPLETE'


def test_raw_usernames_errors_and_unrelated_messages_are_discarded():
    trace = Trace()
    for message in (call(), reply(error=SERVICE + '.Error.AlreadyInUse'),
                    call('DeleteEnrolledFingers'), disconnect(':1.99')):
        trace.feed(message)
    combined = json.dumps([trace.events, trace.summary()])
    assert 'PRIVATE' not in combined and 'DeleteEnrolledFingers' not in combined
    assert ':1.99' not in combined
    altered = status()
    altered['payload']['data'][0] = 'SENSITIVE-UNKNOWN-STATUS'
    assert trace.feed(altered)['status'] == 'UNKNOWN'


def test_daemon_replacement_invalidates_prior_ownership():
    trace = Trace()
    trace.feed(call())
    trace.feed(reply())
    changed = disconnect()
    changed['payload']['data'] = [SERVICE, ':1.10', ':1.20']
    trace.feed(changed)
    assert trace.owners == trace.pending == {}


def test_unique_destination_reply_sender_must_match():
    trace = Trace()
    trace.feed(call(destination=':1.30'))
    with pytest.raises(ValueError, match='Reply sender'):
        trace.feed(reply())


@pytest.mark.parametrize('message', [None, [], 'private', {'type': 'method_call'},
                                   {'type': 'signal', 'payload': ['private']}])
def test_malformed_or_unrelated_input_is_not_evidence(message):
    trace = Trace()
    try:
        trace.feed(message)
    except ValueError:
        pass
    assert trace.events == []


def test_oversized_event_rejected():
    with pytest.raises(ValueError, match='limit'):
        parse_line(b'x' * (256 * 1024 + 1))


def test_collector_only_saves_sanitized_private_files(tmp_path):
    import os
    env = {**os.environ, 'APEX_STATE_DIR': str(tmp_path)}
    data = '\n'.join(json.dumps(m) for m in (call(), reply(), status())) + '\n'
    result = subprocess.run([sys.executable, ROOT / 'tools/fingerprint-observe.py', '--seconds', '2'],
                            input=data, capture_output=True, text=True, env=env, timeout=5)
    assert result.returncode == 0, result.stderr
    files = list((tmp_path / 'fingerprint-observations').rglob('*.json*'))
    assert len(files) == 2
    for path in files:
        assert path.stat().st_mode & 0o077 == 0
        assert 'PRIVATE' not in path.read_text()


def test_collector_rejects_raw_trace_without_retaining_payload(tmp_path):
    import os
    result = subprocess.run([sys.executable, ROOT / 'tools/fingerprint-observe.py', '--seconds', '2'],
                            input='PRIVATE MALFORMED PAYLOAD\n' * 25, capture_output=True, text=True,
                            env={**os.environ, 'APEX_STATE_DIR': str(tmp_path)}, timeout=5)
    assert result.returncode == 2
    report = json.loads(next((tmp_path / 'fingerprint-observations').rglob('summary.json')).read_text())
    assert len(report['errors']) <= 22
    assert 'PRIVATE' not in json.dumps(report)


def test_real_private_busctl_signal_schema(tmp_path):
    if not shutil.which('dbus-run-session') or not shutil.which('busctl'):
        pytest.skip('Private D-Bus fixture tools unavailable; no hardware claim')
    script = '''import subprocess,time,json
p=subprocess.Popen(['busctl','--user','--json=short','--match=interface=net.reactivated.Fprint.Device','--limit-messages=1','monitor'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
time.sleep(.2)
subprocess.run(['busctl','--user','emit','/net/reactivated/Fprint/Device/0','net.reactivated.Fprint.Device','EnrollStatus','sb','enroll-disconnected','true'],check=True)
out,err=p.communicate(timeout=3)
print(out)
'''
    result = subprocess.run(['dbus-run-session', '--', sys.executable, '-c', script],
                            capture_output=True, text=True, timeout=6, check=True)
    trace = Trace()
    trace.feed(parse_line(result.stdout.strip()))
    assert trace.events[0]['status'] == 'enroll-disconnected'
    assert trace.summary()['fingerprint_acceptance'] == 'NOT TESTED'
