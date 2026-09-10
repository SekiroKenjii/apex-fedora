"""Opt-in VM integration checks. Skipped cases are NOT TESTED, never PASS."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import uuid
import pytest
from apexlib.common import ROOT, state_dir, atomic_json, sha256
from apexlib.guesttest import Guest
from apexlib import vm

pytestmark = pytest.mark.integration


@pytest.fixture
def candidate(request):
    disk = os.environ.get('APEX_TEST_DISK')
    key = os.environ.get('APEX_TEST_SSH_KEY')
    user = os.environ.get('APEX_TEST_USER')
    if not all((disk, key, user)):
        pytest.skip('NOT TESTED: provide an isolated test disk and guest SSH credentials')
    directory = state_dir()
    # Refuses to proceed while a builder or another test VM is active.
    vm.start(directory, disk=Path(disk), guest_ssh=True)
    guest = None
    try:
        password = os.environ.get('APEX_TEST_PASSWORD_FILE')
        guest = Guest(directory, user, Path(key), Path(password) if password else None,
                      expected_digest=os.environ.get('APEX_TEST_DIGEST'))
        output = directory / 'vm-tests' / uuid.uuid4().hex
        output.mkdir(parents=True, mode=0o700)
        inputs = {}
        for name in ('tests/integration/test_guest.py', 'tools/apexlib/guesttest.py',
                     'tools/apexlib/vm.py', 'tools/apexlib/common.py', 'tools/apexlib/render.py',
                     'guest/probe.py', 'guest/render-probe.py', 'guest/theme-probe.py',
                     'guest/installed-recovery-probe.py', 'system_files/usr/share/apex/greenboot.conf',
                     'config/project.json', 'pyproject.toml'):
            target = output / 'source' / name
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            shutil.copyfile(ROOT / name, target)
            inputs[name] = sha256(target)
        atomic_json(output / 'context.json', {
            'test': request.node.nodeid, 'digest': guest.expected_digest,
            'vm': vm.alive(directory), 'physical_hardware': False,
            'qemu_version': subprocess.check_output(['qemu-system-x86_64', '--version'], text=True).splitlines()[0],
            'test_account': user, 'password_fixture': bool(password),
            'pytest_version': pytest.__version__, 'source_sha256': inputs,
        })
        print(f'VM evidence: {output}', flush=True)
        guest.wait_ready()
        yield guest, output
    finally:
        if guest is None:
            vm.stop(directory)
        else:
            guest.shutdown()


def test_guest_critical_services_and_screen(candidate):
    guest, output = candidate
    state = guest.critical_health()
    atomic_json(output / 'probe.json', state)
    guest.boot_diagnostics(output)
    guest.screenshot(output / 'screen.ppm')
    # A screenshot capture is evidence, not proof of password login or correct rendering.
    assert (output / 'screen.ppm').stat().st_size > 100


def test_ten_offline_boots(candidate):
    guest, output = candidate
    ids = set()
    for cycle in range(10):
        guest.wait_ready()
        state = guest.critical_health()
        boot_id = guest.run('cat /proc/sys/kernel/random/boot_id').stdout.strip()
        assert boot_id not in ids
        ids.add(boot_id)
        atomic_json(output / f'boot-{cycle}.json', {'boot_id': boot_id, 'observations': state})
        guest.boot_diagnostics(output, f'boot-{cycle}-diagnostics')
        guest.screenshot(output / f'boot-{cycle}.ppm')
        session_output = output / f'boot-{cycle}-desktop'
        session_output.mkdir(mode=0o700)
        guest.password_login_and_render(session_output)
        if cycle < 9:
            guest.reboot()
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                result = guest.run('cat /proc/sys/kernel/random/boot_id', check=False)
                if result.returncode != 0 or result.stdout.strip() != boot_id:
                    break
                time.sleep(2)
            else:
                pytest.fail('Guest did not reboot; do not count the same boot twice')


def test_password_login_and_rendered_wayland_application(candidate):
    guest, output = candidate
    guest.critical_health()
    guest.password_login_and_render(output)


def test_desktop_theme_surfaces(candidate):
    guest, output = candidate
    guest.critical_health()
    guest.password_login_and_render(output)
    guest.theme_surfaces(output)
    guest.boot_diagnostics(output)
    # The operator must review the PNGs before recording desktop.theme-surfaces PASS.


@pytest.mark.skipif(not os.environ.get('APEX_FINGERPRINT_IMAGE_TEST'), reason='NOT TESTED: select the fingerprint experiment explicitly')
def test_fingerprint_image_desktop_and_recovery_configuration(candidate):
    guest, output = candidate
    guest.critical_health()
    expected = {'libfprint': '1.94.100-1.fc44.apex1',
                'gnome-control-center': '50.4-1.fc44.apex1',
                'gnome-control-center-filesystem': '50.4-1.fc44.apex1'}
    for name, version in expected.items():
        assert guest.run(f"rpm -q --qf '%{{VERSION}}-%{{RELEASE}}' {name}").stdout == version
    guest.password_login_and_render(output)
    guest.run('systemctl --user stop apex-render-probe')
    source = ROOT / 'guest/installed-recovery-probe.py'
    guest.run('install -m 0600 /dev/stdin /var/tmp/apex-installed-recovery-probe.py', input=source.read_text())
    checksum = sha256(ROOT / 'system_files/usr/share/apex/greenboot.conf')
    result = guest.sudo(f'python3 /var/tmp/apex-installed-recovery-probe.py {guest.expected_digest} {checksum}')
    atomic_json(output / 'installed-recovery-execution.json', {
        'source_sha256': sha256(source), 'returncode': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr})
    assert result.returncode == 0
    assert json.loads(result.stdout)['status'] == 'PASS'
    guest.run('systemd-run --user --unit=apex-settings-smoke --collect --setenv=GDK_BACKEND=wayland gnome-control-center system')
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        result = guest.run('busctl --user call org.freedesktop.DBus /org/freedesktop/DBus org.freedesktop.DBus GetConnectionUnixProcessID s org.gnome.Settings', check=False)
        if result.returncode == 0:
            break
        time.sleep(1)
    assert result.returncode == 0
    time.sleep(3)
    guest.screenshot(output / 'settings.png')
    atomic_json(output / 'fingerprint-image.json', {'digest': guest.expected_digest, 'packages': expected,
        'settings_dbus_pid': result.stdout.strip(), 'journal': guest.run('journalctl --user -u apex-settings-smoke --no-pager').stdout,
        'hardware': 'NOT TESTED', 'settings_visual_review': 'NOT TESTED', 'recovery_faults': 'NOT TESTED'})
    guest.boot_diagnostics(output)


def test_failed_deployment_rolls_back_within_two_attempts():
    pytest.skip('NOT TESTED: requires two trusted bootc deployments and GRUB failure evidence')
