from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import time

from .common import ROOT, Blocked, atomic_json, regular_file
from .vm import QMP, alive

SHELL_STARTED = 'f3ea493c22934e26811cd62abe8e203a'


def shell_started(text: str, pid: int) -> dict | None:
    for line in text.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict) and event.get('MESSAGE_ID') == SHELL_STARTED and event.get('_PID') == str(pid):
            return event
    return None


def assert_candidate(status: dict, expected: str):
    booted = status.get('status', {}).get('booted') or {}
    image = booted.get('image') or {}
    if not re.fullmatch(r'sha256:[a-f0-9]{64}', expected) or image.get('imageDigest') != expected:
        raise AssertionError('Booted OCI digest does not match the selected candidate')


class Guest:
    """Talk only to a running Apex test VM. Never accepts a host address."""
    def __init__(self, directory: Path, user: str, key: Path, password_file: Path | None = None, *, expected_digest: str | None = None):
        info = alive(directory)
        if not info or info['role'] != 'test':
            raise Blocked('Guest tests require the test VM, not the builder or host')
        if not re.fullmatch(r'[a-z_][a-z0-9_-]*', user):
            raise Blocked('Invalid test account name')
        if not any('127.0.0.1:22245-:22' in arg for arg in info['command']):
            raise Blocked('Start the test VM with its localhost SSH port enabled')
        key = regular_file(key, within=directory)
        self.directory = directory
        self.vm_info = info
        self.user = user
        self.expected_digest = expected_digest or json.loads(regular_file(directory / 'candidate.json', within=directory).read_text())['digest']
        if not re.fullmatch(r'sha256:[a-f0-9]{64}', self.expected_digest):
            raise Blocked('Guest tests require an explicit immutable OCI digest')
        self.artifacts_dir = Path(info['artifacts_dir'])
        if not self.artifacts_dir.resolve().is_relative_to(directory.resolve()):
            raise Blocked('VM evidence path escapes runtime storage')
        self.password_file = regular_file(password_file, within=directory) if password_file else None
        known_hosts = Path(info['artifacts_dir']) / 'known-hosts'
        self.connection = ['ssh', '-i', str(key), '-p', '22245', '-o', 'BatchMode=yes', '-o', 'IdentitiesOnly=yes', '-o', 'ConnectTimeout=3', '-o', 'StrictHostKeyChecking=accept-new', '-o', f'UserKnownHostsFile={known_hosts}', f'{user}@127.0.0.1']

    def run(self, command, *, input=None, timeout=25, check=True):
        self.check_vm()
        return subprocess.run(self.connection + [command], input=input, text=True, capture_output=True, timeout=timeout, check=check)

    def check_vm(self):
        if alive(self.directory) != self.vm_info:
            raise Blocked('The test VM stopped or changed; create a new guest connection')

    def wait_ready(self, timeout=240):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            result = self.run('systemd-detect-virt --vm', check=False)
            if result.returncode == 0 and result.stdout.strip() in {'kvm', 'qemu'}:
                state = self.run('systemctl is-system-running', check=False).stdout.strip()
                if state in {'running', 'degraded'}:
                    return
            time.sleep(2)
        raise Blocked('Guest SSH did not become ready; retain serial and QMP evidence')

    def reboot(self):
        return self.sudo('systemctl reboot')

    def shutdown(self):
        """Power off this guest without relying on desktop power-key policy."""
        self.check_vm()
        result = self.sudo('systemctl --no-block poweroff')
        proof = {'method': 'guest systemctl poweroff over private SSH',
                 'digest': self.expected_digest, 'pid': self.vm_info['pid'],
                 'request_returncode': result.returncode, 'status': 'BLOCKED'}
        atomic_json(self.artifacts_dir / 'shutdown.json', proof)
        # SSH may close during shutdown. Only the owned VM exiting proves completion.
        if result.returncode not in (0, 255):
            raise Blocked('Guest rejected shutdown; VM and evidence are retained')
        for _ in range(45):
            current = alive(self.directory)
            if current is None:
                proof['status'] = 'PASS'
                atomic_json(self.artifacts_dir / 'shutdown.json', proof)
                return
            if current != self.vm_info:
                raise Blocked('VM identity changed while waiting for shutdown')
            time.sleep(1)
        raise Blocked('Guest did not power off within 45 seconds; it remains running')

    def sudo(self, command):
        if self.password_file:
            secret = json.loads(self.password_file.read_text())['password']
            return self.run('sudo -S -p "" ' + command, input=secret + '\n', check=False)
        return self.run('sudo -n ' + command, check=False)

    def probe(self):
        result = self.run('python3 -', input=(ROOT / 'guest/probe.py').read_text())
        data = json.loads(result.stdout)
        status = self.sudo('bootc status --format json')
        data['observations']['bootc'] = {'returncode': status.returncode, 'stdout': status.stdout.strip(), 'stderr': status.stderr.strip()}
        return data

    def screenshot(self, path: Path):
        self.check_vm()
        if not path.resolve().is_relative_to(self.directory.resolve()):
            raise Blocked('Screenshots must stay inside runtime storage')
        connection = QMP(self.directory / 'qmp.sock')
        try:
            arguments = {'filename': str(path.resolve())}
            if path.suffix == '.png':
                arguments['format'] = 'png'
            connection.call('screendump', arguments)
        finally:
            connection.close()

    def keys(self, *codes):
        self.check_vm()
        connection = QMP(self.directory / 'qmp.sock')
        try:
            connection.call('send-key', {'keys': [{'type': 'qcode', 'data': code} for code in codes], 'hold-time': 40})
        finally:
            connection.close()

    def seat_session(self, account=None, *, session_class=None):
        for row in self.run('loginctl list-sessions --no-legend --no-pager').stdout.splitlines():
            columns = row.split()
            if len(columns) > 3 and (account is None or columns[2] == account) and columns[3] == 'seat0':
                if re.fullmatch('[a-zA-Z0-9]+', columns[0]):
                    if session_class is not None:
                        value = self.run(f'loginctl show-session {columns[0]} -p Class --value').stdout.strip()
                        if value != session_class:
                            continue
                    return columns[0]
        return None

    def wait_overview(self, expected: bool):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            result = self.run('busctl --user get-property org.gnome.Shell /org/gnome/Shell org.gnome.Shell OverviewActive', check=False)
            if result.returncode == 0 and result.stdout.strip() == f'b {str(expected).lower()}':
                return
            time.sleep(.5)
        raise AssertionError(f'Shell Overview did not become {expected}; retain the console evidence')

    def prepare_desktop(self, output: Path):
        deadline = time.monotonic() + 90
        event = None
        while time.monotonic() < deadline:
            owner = self.run('busctl --user call org.freedesktop.DBus /org/freedesktop/DBus org.freedesktop.DBus GetConnectionUnixProcessID s org.gnome.Shell', check=False)
            match = re.fullmatch(r'u ([1-9][0-9]*)', owner.stdout.strip())
            if owner.returncode == 0 and match:
                pid = int(match[1])
                journal = self.run(f'journalctl --user -b MESSAGE_ID={SHELL_STARTED} _PID={pid} -n 1 -o json --no-pager')
                event = shell_started(journal.stdout, pid)
                if event:
                    break
            time.sleep(1)
        else:
            raise AssertionError('The active GNOME Shell did not report startup completion')
        # GNOME 50 opens Welcome in startup-complete; Escape is its Skip action.
        time.sleep(1)
        self.screenshot(output / 'shell-startup.png')
        self.keys('esc')
        time.sleep(1)
        self.keys('esc')
        self.wait_overview(False)
        self.keys('meta_l')
        self.wait_overview(True)
        self.screenshot(output / 'overview.png')
        self.keys('esc')
        self.wait_overview(False)
        atomic_json(output / 'shell-input.json', {
            'startup': event, 'welcome_action': 'Escape after Shell startup',
            'overview_keyboard_roundtrip': 'PASS', 'dbus_used_for': 'read-only state verification'})

    def password_login_and_render(self, output: Path):
        if not self.password_file:
            raise Blocked('A GUI password test needs the disposable account credentials')
        if self.seat_session(self.user):
            raise Blocked('The fixture is already logged in; cannot prove password login')
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if self.seat_session(session_class='greeter'):
                break
            time.sleep(1)
        else:
            raise AssertionError('GDM did not create a seat0 greeter session')
        # Give the greeter its first frame before sending keyboard input.
        time.sleep(3)
        self.screenshot(output / 'greeter.ppm')
        self.screenshot(output / 'greeter.png')
        self.keys('ret')
        time.sleep(1)
        secret = json.loads(self.password_file.read_text())['password']
        for ch in secret:
            if not ch.isascii() or not (ch.isalnum() or ch in '-_'):
                raise Blocked('Unsupported test password character for QMP keyboard input')
            code = 'minus' if ch in '-_' else ch.lower()
            self.keys(*(['shift'] if ch.isupper() or ch == '_' else []), code)
            time.sleep(.1)
        self.keys('ret')
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            session = self.seat_session(self.user)
            if session and self.run(f'loginctl show-session {session} -p Type --value').stdout.strip() == 'wayland':
                break
            time.sleep(1)
        else:
            raise AssertionError('No Wayland user session appeared after password entry')
        atomic_json(output / 'login.json', {'method': 'GDM password through QMP', 'user': self.user, 'session': session, 'type': 'wayland'})
        self.prepare_desktop(output)
        self.run('install -m 0600 /dev/stdin /var/tmp/apex-render-probe.py', input=(ROOT / 'guest/render-probe.py').read_text())
        self.run('systemd-run --user --unit=apex-render-probe --collect --setenv=GDK_BACKEND=wayland python3 /var/tmp/apex-render-probe.py')
        from .render import swatches
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            self.keys('esc')
            time.sleep(1)
            self.screenshot(output / 'application.ppm')
            try:
                result = swatches(output / 'application.ppm')
                break
            except AssertionError:
                time.sleep(1)
        else:
            raise AssertionError('GTK4 application did not visibly render its test bars')
        journal = self.run('journalctl --user -u apex-render-probe --no-pager').stdout
        assert 'GdkWaylandDisplay' in journal
        self.screenshot(output / 'application.png')
        atomic_json(output / 'render.json', {'digest': self.expected_digest, 'pixels': result, 'journal': journal})

    def critical_health(self):
        result = self.probe()['observations']
        atomic_json(self.artifacts_dir / 'last-probe.json', {'expected_digest': self.expected_digest, 'observations': result})
        for check in ('gdm', 'bootc', 'dbus', 'root_mount', 'failed_units', 'selinux', 'kernel'):
            if result[check]['returncode'] != 0:
                raise AssertionError(f'Guest {check} failed: {result[check]}')
        assert result['gdm']['stdout'] == 'active'
        assert_candidate(json.loads(result['bootc']['stdout']), self.expected_digest)
        assert result['selinux']['stdout'] == 'Enforcing'
        assert result['failed_units']['stdout'] == ''
        return result

    def theme_surfaces(self, output: Path):
        self.run('install -m 0600 /dev/stdin /var/tmp/apex-theme-probe.py', input=(ROOT / 'guest/theme-probe.py').read_text())
        observations = {'digest': self.expected_digest, 'visual_review': 'NOT TESTED', 'probes': {}}
        for mode in ('gtk3', 'adwaita'):
            unit = f'apex-theme-{mode}'
            self.run(f'systemd-run --user --unit={unit} --collect --setenv=GDK_BACKEND=wayland python3 /var/tmp/apex-theme-probe.py {mode}')
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                journal = self.run(f'journalctl --user -u {unit} --no-pager').stdout
                if 'window-presented' in journal:
                    break
                time.sleep(1)
            else:
                atomic_json(output / f'{mode}-failure.json', {'journal': journal})
                raise AssertionError(f'{mode} theme probe did not present a window')
            time.sleep(3)
            self.keys('esc')
            self.screenshot(output / f'{mode}.png')
            observations['probes'][mode] = journal
            self.run(f'systemctl --user stop {unit}')
        self.screenshot(output / 'shell-before.ppm')
        self.keys('meta_l', 's')
        time.sleep(2)
        self.screenshot(output / 'shell-surface.ppm')
        self.screenshot(output / 'shell-surface.png')
        from .render import surface_change
        observations['shell_change'] = surface_change(output / 'shell-before.ppm', output / 'shell-surface.ppm')
        self.keys('esc')
        observations['gtk_theme'] = self.run('gsettings get org.gnome.desktop.interface gtk-theme').stdout.strip()
        observations['shell_theme'] = self.run('gsettings get org.gnome.shell.extensions.user-theme name').stdout.strip()
        observations['extensions'] = self.run('gnome-extensions list --enabled').stdout.strip()
        observations['composition'] = json.loads(self.run('cat /usr/share/apex/shell-theme-source.json').stdout)
        assert observations['gtk_theme'] == "'Adwaita-dark'"
        assert observations['shell_theme'] == "'Shadcn-Graphite'"
        atomic_json(output / 'theme-surfaces.json', observations)

    def boot_diagnostics(self, output: Path, name='boot-diagnostics'):
        if not re.fullmatch('[a-z0-9-]+', name) or not output.resolve().is_relative_to(self.directory.resolve()):
            raise Blocked('Invalid boot evidence destination')
        commands = {
            'kernel': 'journalctl -b -k --no-pager',
            'warnings': 'journalctl -b -p warning --no-pager',
            'greenboot': 'journalctl -b -u greenboot-healthcheck -u greenboot-set-rollback-trigger --no-pager',
            'health_state': 'systemctl show greenboot-healthcheck.service -p Result -p ActiveState -p ExecMainStatus',
            'grubenv': 'grub2-editenv /boot/grub2/grubenv list',
            'boot_entries': 'ls -l /boot/loader/entries',
            'cmdline': 'cat /proc/cmdline',
            'clocksource': 'grep -H . /sys/devices/system/clocksource/clocksource0/current_clocksource /sys/devices/system/clocksource/clocksource0/available_clocksource',
            'watchdog_device': 'grep -H . /sys/class/watchdog/watchdog0/identity /sys/class/watchdog/watchdog0/state /sys/class/watchdog/watchdog0/nowayout /sys/class/watchdog/watchdog0/timeout',
            'watchdog_manager': 'systemctl show -p RuntimeWatchdogUSec -p RebootWatchdogUSec -p KExecWatchdogUSec',
        }
        observations = {}
        for key, command in commands.items():
            result = self.sudo(command)
            observations[key] = {'returncode': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr}
        atomic_json(output / f'{name}.json', {'digest': self.expected_digest, 'observations': observations})
        return observations
