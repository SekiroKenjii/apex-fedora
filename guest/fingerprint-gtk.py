"""Compile and exercise the full GNOME fingerprint dialog in the Fedora builder."""
import hashlib
import json
import os
from pathlib import Path
import select
import shlex
import subprocess
import sys
import tarfile

CASES = ('error-cancel-retry', 'error-close', 'cancel-twice', 'close-pending', 'daemon-replace')


def summary_status(variants):
    if set(variants) != {'original', 'patched'} or any(set(cases) != set(CASES) for cases in variants.values()):
        return 'FAIL'
    passed = all(c['status'] == 'PASS' and c.get('ready') and c['returncode'] == 0
                 for c in variants['patched'].values())
    reproduced = all(variants['original'][c]['status'] == 'FAIL'
                     and variants['original'][c].get('ready')
                     and variants['original'][c].get('assertion_failure')
                     for c in ('error-cancel-retry', 'error-close', 'cancel-twice'))
    return 'PASS' if passed and reproduced else 'FAIL'


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def run(args, **kwargs):
    return subprocess.run([str(a) for a in args], check=True, **kwargs)


def compile_dialog(source, work, variant):
    users = source / 'panels/system/users'
    common = source / 'panels/common'
    work.mkdir()
    (work / 'config.h').write_text('#define GETTEXT_PACKAGE "gnome-control-center"\n#define GNOMELOCALEDIR "/usr/share/locale"\n')
    run(['gdbus-codegen', '--interface-prefix', 'net.reactivated.Fprint.', '--c-namespace', 'CcFprintd',
         '--c-generate-autocleanup', 'all', '--generate-c-code', work / 'cc-fprintd-generated',
         users / 'data/net.reactivated.Fprint.Manager.xml', users / 'data/net.reactivated.Fprint.Device.xml'])
    header = users / 'cc-fingerprint-manager.h'
    with (work / 'cc-user-accounts-enum-types.h').open('w') as output:
        run(['glib-mkenums', '--identifier-prefix', 'Cc', '--symbol-prefix', 'cc',
             '--fhead', '#pragma once\n#include <glib-object.h>\n',
             '--vhead', 'GType @enum_name@_get_type (void);\n#define @ENUMPREFIX@_TYPE_@ENUMSHORT@ (@enum_name@_get_type())\n', header], stdout=output)
    with (work / 'enums.c').open('w') as output:
        run(['glib-mkenums', '--identifier-prefix', 'Cc', '--symbol-prefix', 'cc',
             '--fhead', '#include "cc-fingerprint-manager.h"\n',
             '--vhead', 'GType @enum_name@_get_type(void) { static GType type; if (!type) { static const GEnumValue values[] = {',
             '--vprod', '{@VALUENAME@, "@VALUENAME@", "@valuenick@"},',
             '--vtail', '{0, NULL, NULL}}; type = g_enum_register_static("@EnumName@", values); } return type; }', header], stdout=output)
    resource = '<gresources>'
    for prefix, stem, directory in (
            ('/org/gnome/control-center/system/users', 'cc-fingerprint-dialog', users),
            ('/org/gnome/control-center/common', 'cc-list-row', common)):
        run(['blueprint-compiler', 'compile', '--output', work / (stem + '.ui'), directory / (stem + '.blp')])
        resource += f'<gresource prefix="{prefix}"><file>{stem}.ui</file></gresource>'
    (work / 'resources.xml').write_text(resource + '</gresources>')
    for kind, suffix in (('header', 'h'), ('source', 'c')):
        run(['glib-compile-resources', '--generate-' + kind, '--c-name', 'cc_common',
             '--sourcedir', work, '--target', work / ('cc-common-resources.' + suffix), work / 'resources.xml'])
    flags = shlex.split(subprocess.check_output(['pkg-config', '--cflags', '--libs',
                                                'gtk4', 'libadwaita-1', 'accountsservice'], text=True))
    run(['gcc', '-g', '-O1', '-Wall', '-Werror=implicit-function-declaration',
         '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
         '-I' + str(work), '-I' + str(users), '-I' + str(common),
         Path('guest/fingerprint-gtk.c').resolve(), users / 'cc-fingerprint-manager.c', common / 'cc-list-row.c',
         work / 'cc-fprintd-generated.c', work / 'enums.c', work / 'cc-common-resources.c',
         *flags, '-lm', '-o', work / 'dialog-test'])


def case(binary, scenario, directory):
    directory.mkdir()
    processes = []
    try:
        with (directory / 'bus.log').open('w') as bus_log:
            bus = subprocess.Popen(['dbus-daemon', '--session', '--nofork', '--print-address=1'],
                                   stdout=subprocess.PIPE, stderr=bus_log, text=True)
            processes.append(bus)
            if not select.select([bus.stdout], [], [], 5)[0]:
                raise RuntimeError('Private D-Bus did not start')
            address = bus.stdout.readline().strip()
        env = {k: v for k, v in os.environ.items() if not k.startswith(('DBUS_', 'FP_', 'G_MESSAGES_', 'GTK_', 'GDK_'))}
        env.update(DBUS_SYSTEM_BUS_ADDRESS=address, DBUS_SESSION_BUS_ADDRESS=address,
                   GDK_BACKEND='x11', GSK_RENDERER='cairo', GTK_A11Y='none', LC_ALL='C.UTF-8',
                   ASAN_OPTIONS='detect_leaks=0:abort_on_error=1', UBSAN_OPTIONS='halt_on_error=1',
                   GSETTINGS_BACKEND='memory')
        with (directory / 'service.log').open('w') as log:
            service = subprocess.Popen([sys.executable, 'guest/fingerprint-gtk-service.py'], env=env,
                                       stdout=subprocess.PIPE, stderr=log, text=True)
            processes.append(service)
            if not select.select([service.stdout], [], [], 5)[0] or service.stdout.readline().strip() != 'READY':
                raise RuntimeError('Private mock service did not start')
            with (directory / 'dialog.log').open('w') as dialog_log:
                result = subprocess.run(['xvfb-run', '-a', '-s', '-screen 0 1024x768x24 -nolisten tcp',
                                         str(binary), scenario], env=env, stdout=dialog_log,
                                        stderr=subprocess.STDOUT, timeout=45)
        text = (directory / 'dialog.log').read_text()
        passed = result.returncode == 0 and f'PASS {scenario}\n' in text
        return {'status': 'PASS' if passed else 'FAIL', 'returncode': result.returncode,
                'ready': f'READY {scenario}\n' in text,
                'assertion_failure': 'Bail out! ERROR:' in text,
                'log_sha256': sha(directory / 'dialog.log')}
    finally:
        for process in reversed(processes):
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def main():
    if (os.geteuid() == 0 or not Path('/etc/apex-builder').is_file()
            or subprocess.check_output(['systemd-detect-virt', '--vm'], text=True).strip() not in {'kvm', 'qemu'}):
        raise RuntimeError('Requires an unprivileged user in the isolated builder VM')
    request = json.loads(Path('request.json').read_text())
    for name, checksum in request['inputs'].items():
        if sha(name) != checksum:
            raise ValueError('Input checksum mismatch: ' + name)
    lock = json.loads(Path('config/fingerprint-rpms.lock.json').read_text())
    package = next(p for p in lock['packages'] if p['name'] == 'gnome-control-center')
    archive = Path('inputs') / package['archive']
    if sha(archive) != package['archive_sha256']:
        raise ValueError('GNOME archive checksum mismatch')
    output = Path('output').resolve()
    output.mkdir()
    report = {'status': 'FAIL', 'scope': 'complete GTK dialog and manager; private mocked D-Bus',
              'hardware': 'NOT TESTED', 'packaged_gnome_binary': 'NOT TESTED',
              'leak_detection': 'disabled for GTK process-global allocations',
              'source_sha256': sha(archive), 'patch_sha256': sha(Path(package['patch'])),
              'inputs': request['inputs'], 'variants': {}}
    try:
        report['environment'] = subprocess.check_output(['rpm', '-q', 'gtk4', 'libadwaita', 'accountsservice-libs',
            'glib2', 'gcc', 'blueprint-compiler', 'dbus-daemon', 'python3-dbus', 'xorg-x11-server-Xvfb'], text=True).splitlines()
        for variant in ('original', 'patched'):
            extracted = Path('source-' + variant).resolve()
            extracted.mkdir()
            results_dir = output / variant
            results_dir.mkdir()
            with tarfile.open(archive) as source_tar:
                source_tar.extractall(extracted, filter='data')
            source = extracted / 'gnome-control-center-50.4'
            if variant == 'patched':
                run(['patch', '--batch', '--fuzz=0', '-p1', '-i', Path(package['patch']).resolve()], cwd=source)
            work = results_dir / 'compiled'
            compile_dialog(source, work, variant)
            results = report['variants'][variant] = {}
            for scenario in CASES:
                results[scenario] = case(work / 'dialog-test', scenario, results_dir / scenario)
                print(variant, scenario, results[scenario]['status'], flush=True)
        report['status'] = summary_status(report['variants'])
    finally:
        (output / 'results.json').write_text(json.dumps(report, indent=2) + '\n')
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
