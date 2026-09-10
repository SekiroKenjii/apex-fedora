import json
import pytest
from types import SimpleNamespace
from apexlib.guesttest import Guest, assert_candidate, shell_started, SHELL_STARTED
from apexlib import guesttest
from apexlib.common import Blocked

DIGEST = 'sha256:' + 'a' * 64


def test_explicit_experiment_does_not_change_candidate(tmp_path, monkeypatch):
    key = tmp_path / 'key'
    key.write_text('test fixture')
    old = json.dumps({'digest': 'sha256:' + 'b' * 64})
    (tmp_path / 'candidate.json').write_text(old)
    monkeypatch.setattr(guesttest, 'alive', lambda _: {
        'role': 'test', 'command': ['hostfwd=tcp:127.0.0.1:22245-:22'], 'artifacts_dir': str(tmp_path)})
    guest = Guest(tmp_path, 'testuser', key, expected_digest=DIGEST)
    assert guest.expected_digest == DIGEST
    assert (tmp_path / 'candidate.json').read_text() == old
    with pytest.raises(Blocked, match='immutable OCI digest'):
        Guest(tmp_path, 'testuser', key, expected_digest='latest')


def test_shell_startup_requires_the_active_process_and_message_id():
    event = {'_PID': '3154', 'MESSAGE_ID': SHELL_STARTED}
    assert shell_started(json.dumps(event), 3154) == event
    assert shell_started(json.dumps(event), 1428) is None
    assert shell_started(json.dumps(event | {'MESSAGE_ID': 'other'}), 3154) is None
    assert shell_started('-- No entries --\n[]\nnull', 3154) is None


@pytest.mark.parametrize('expected', [True, False])
def test_overview_poll_uses_read_only_state_and_expected_value(monkeypatch, expected):
    guest = Guest.__new__(Guest)
    values = iter([f'b {str(not expected).lower()}', f'b {str(expected).lower()}'])
    calls = []
    guest.run = lambda command, **_: (calls.append(command) or SimpleNamespace(returncode=0, stdout=next(values)))
    monkeypatch.setattr(guesttest.time, 'sleep', lambda _: None)
    guest.wait_overview(expected)
    assert len(calls) == 2
    assert all('get-property' in command and 'OverviewActive' in command for command in calls)


def test_overview_timeout_does_not_count_as_interactive_desktop(monkeypatch):
    guest = Guest.__new__(Guest)
    guest.run = lambda *_, **__: SimpleNamespace(returncode=0, stdout='b false')
    ticks = iter([0, 0, 16])
    monkeypatch.setattr(guesttest.time, 'monotonic', lambda: next(ticks))
    monkeypatch.setattr(guesttest.time, 'sleep', lambda _: None)
    with pytest.raises(AssertionError, match='Overview did not become'):
        guest.wait_overview(True)


def test_booted_digest_matches_candidate():
    assert_candidate({'status': {'booted': {'image': {'imageDigest': DIGEST}}}}, DIGEST)


@pytest.mark.parametrize('status', [
    {}, {'status': {'booted': None}},
    {'status': {'booted': {'image': {'imageDigest': 'sha256:' + 'b'*64}}}},
    {'status': {'staged': {'image': {'imageDigest': DIGEST}}, 'booted': None}},
    {'status': {'rollback': {'image': {'imageDigest': DIGEST}}, 'booted': None}},
])
def test_wrong_or_only_staged_digest_is_not_a_candidate_boot(status):
    with pytest.raises(AssertionError, match='Booted OCI digest'):
        assert_candidate(status, DIGEST)


@pytest.mark.parametrize('account', ['gdm', 'gdm-greeter'])
def test_greeter_is_selected_by_session_class_not_account_name(account):
    guest = Guest.__new__(Guest)
    guest.run = lambda command: SimpleNamespace(stdout=(
        f'1 60578 {account} - 1033 manager-early - no -\n'
        f'c1 60578 {account} seat0 1004 greeter tty1 no -\n'
        if command.startswith('loginctl list-sessions') else 'greeter\n'
    ))
    assert guest.seat_session(session_class='greeter') == 'c1'


def test_ssh_session_does_not_count_as_graphical_password_login():
    guest = Guest.__new__(Guest)
    guest.run = lambda command: SimpleNamespace(stdout='7 1000 apex-test - 2577 user - no -\n')
    assert guest.seat_session('apex-test') is None


@pytest.mark.parametrize('replacement', [None, {'role': 'test', 'pid': 2}, {'role': 'builder', 'pid': 1}])
@pytest.mark.parametrize('operation', ['run', 'keys', 'screenshot'])
def test_stale_guest_cannot_control_another_vm(tmp_path, monkeypatch, replacement, operation):
    guest = Guest.__new__(Guest)
    guest.directory = tmp_path
    guest.vm_info = {'role': 'test', 'pid': 1}
    monkeypatch.setattr(guesttest, 'alive', lambda _: replacement)
    with pytest.raises(Blocked, match='stopped or changed'):
        getattr(guest, operation)(tmp_path / 'screen.png' if operation == 'screenshot' else 'ret')


def shutdown_guest(tmp_path, monkeypatch, states, returncode=0):
    guest = Guest.__new__(Guest)
    guest.directory = guest.artifacts_dir = tmp_path
    guest.vm_info = {'role': 'test', 'pid': 17}
    guest.expected_digest = DIGEST
    calls = []
    guest.sudo = lambda command: (calls.append(command) or SimpleNamespace(returncode=returncode))
    state = iter(states)
    monkeypatch.setattr(guesttest, 'alive', lambda _: next(state))
    monkeypatch.setattr(guesttest.time, 'sleep', lambda _: None)
    return guest, calls


@pytest.mark.parametrize('returncode', [0, 255])
def test_shutdown_requires_vm_exit_even_if_ssh_disconnected(tmp_path, monkeypatch, returncode):
    info = {'role': 'test', 'pid': 17}
    guest, calls = shutdown_guest(tmp_path, monkeypatch, [info, info, None], returncode)
    guest.shutdown()
    assert calls == ['systemctl --no-block poweroff']
    assert json.loads((tmp_path / 'shutdown.json').read_text())['status'] == 'PASS'


@pytest.mark.parametrize('replacement', [None, {'role': 'builder', 'pid': 18}])
def test_shutdown_refuses_stale_guest_before_power_command(tmp_path, monkeypatch, replacement):
    guest, calls = shutdown_guest(tmp_path, monkeypatch, [replacement])
    with pytest.raises(Blocked, match='stopped or changed'):
        guest.shutdown()
    assert calls == []


def test_shutdown_rejects_vm_replacement_while_waiting(tmp_path, monkeypatch):
    guest, calls = shutdown_guest(tmp_path, monkeypatch, [
        {'role': 'test', 'pid': 17}, {'role': 'builder', 'pid': 18}])
    with pytest.raises(Blocked, match='identity changed'):
        guest.shutdown()
    assert len(calls) == 1
    assert json.loads((tmp_path / 'shutdown.json').read_text())['status'] == 'BLOCKED'


def test_shutdown_timeout_never_forces_guest_exit(tmp_path, monkeypatch):
    guest, calls = shutdown_guest(tmp_path, monkeypatch, [{'role': 'test', 'pid': 17}] * 46)
    with pytest.raises(Blocked, match='remains running'):
        guest.shutdown()
    assert calls == ['systemctl --no-block poweroff']
    assert json.loads((tmp_path / 'shutdown.json').read_text())['status'] == 'BLOCKED'


def test_shutdown_rejected_by_guest_retains_blocked_proof(tmp_path, monkeypatch):
    guest, _ = shutdown_guest(tmp_path, monkeypatch, [{'role': 'test', 'pid': 17}], returncode=1)
    with pytest.raises(Blocked, match='rejected shutdown'):
        guest.shutdown()
    assert json.loads((tmp_path / 'shutdown.json').read_text())['status'] == 'BLOCKED'
