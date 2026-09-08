import pytest
from types import SimpleNamespace
from apexlib.guesttest import Guest, assert_candidate
from apexlib import guesttest
from apexlib.common import Blocked

DIGEST = 'sha256:' + 'a' * 64


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
