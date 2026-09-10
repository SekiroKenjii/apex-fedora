from __future__ import annotations

import fcntl
import json
from pathlib import Path
import re
import shlex
import subprocess
import uuid

from .common import ROOT, Blocked, atomic_json, regular_file, run, sha256
from .pipeline import export_source
from .vm import ssh_args


def target(directory: Path, build_id: str):
    if not re.fullmatch(r'[a-f0-9]{32}', build_id):
        raise Blocked('NVIDIA packaging requires a completed Fedora image build ID')
    previous = directory / 'exports' / build_id
    result = json.loads(regular_file(previous / 'result.json', within=directory).read_text())
    if result.get('status') != 'PASS' or result.get('kind') != 'image':
        raise Blocked('NVIDIA packaging requires a completed image build')
    frozen = json.loads(regular_file(previous / 'output/image.json', within=directory).read_text())
    manifest = regular_file(previous / 'output/manifest.json', within=directory)
    if (frozen.get('profile') != 'fedora'
            or frozen.get('digest') != 'sha256:' + sha256(manifest)
            or not re.fullmatch(r'sha256:[a-f0-9]{64}', frozen.get('image_id', ''))
            or json.loads(manifest.read_text()).get('config', {}).get('digest') != frozen['image_id']):
        raise Blocked('Frozen Fedora image identity mismatch')
    lock = json.loads((ROOT / 'config/nvidia.lock.json').read_text())
    compiler = regular_file(previous / 'output/kernel-config.txt', within=directory).read_text()
    if re.findall(r'^CONFIG_CC_VERSION_TEXT="([^"]+)"$', compiler, re.M) != [lock['compiler_text']]:
        raise Blocked('NVIDIA compiler lock differs from the frozen image')
    return frozen


def verify_report(export: Path, frozen: dict, lock_hash: str):
    out = export / 'output/nvidia'
    report = json.loads(regular_file(out / 'results.json', within=export).read_text())
    if (report.get('status') != 'PASS' or report.get('stage') != 'rpm-build'
            or report.get('image_id') != frozen['image_id'] or report.get('source_lock_sha256') != lock_hash
            or report.get('ready_to_install') is not False
            or any(report.get(name) != 'NOT TESTED' for name in
                   ('image_integration', 'initramfs', 'hardware', 'secure_boot'))):
        raise Blocked('NVIDIA packaging did not produce a bound RPM-only result')
    artifacts = report.get('artifacts', {})
    if not artifacts or 'sources/nvidia.lock.json' not in artifacts:
        raise Blocked('NVIDIA build output is incomplete')
    for relative, expected in artifacts.items():
        path = Path(relative)
        if path.is_absolute() or '..' in path.parts or path.as_posix() != relative:
            raise Blocked('NVIDIA artifact path escapes its output')
        if sha256(regular_file(out / path, within=out)) != expected:
            raise Blocked('Transferred NVIDIA artifact checksum mismatch')
    lock = json.loads((out / 'sources/nvidia.lock.json').read_text())
    if (artifacts['sources/nvidia.lock.json'] != lock_hash
            or report.get('kernel_release') != lock['kernel_release'] or report.get('version') != lock['version']):
        raise Blocked('Transferred NVIDIA lock differs from the build input')
    expected_rpms = {'packages/{name}-{version}-{release}.{arch}.rpm'.format(**p) for p in lock['packages']}
    expected_rpms.add(f'packages/kmod-apex-nvidia-open-{lock["version"]}-1.fc44.x86_64.rpm')
    actual_rpms = {name for name in artifacts if name.startswith('packages/') and name.endswith('.rpm')}
    if actual_rpms != expected_rpms:
        raise Blocked('NVIDIA package set is incomplete')
    for package in lock['packages']:
        name = 'packages/{name}-{version}-{release}.{arch}.rpm'.format(**package)
        if artifacts[name] != package['sha256']:
            raise Blocked('NVIDIA vendor package differs from its source lock')
    return report


def execute(directory: Path, build_id: str):
    frozen = target(directory, build_id)
    with (directory / 'build.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Blocked('Wait for the active build before packaging NVIDIA')
        connection = ssh_args(directory)
        run_id = uuid.uuid4().hex
        export = directory / 'nvidia-builds' / run_id
        export.mkdir(parents=True, mode=0o700)
        bundle = export / 'source.tar'
        manifest = export_source(bundle)
        atomic_json(export / 'source-manifest.json', manifest)
        atomic_json(export / 'target-image.json', frozen)
        remote = f'/var/tmp/apex-nvidia-{run_id}'
        run(connection + [f'mkdir -m 700 {remote}'])
        scp = ['scp', '-i', str(directory / 'builder_ed25519'), '-P', connection[4],
               '-o', 'IdentitiesOnly=yes', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
               '-o', f'UserKnownHostsFile={directory}/known_hosts']
        run(scp + [bundle, export / 'target-image.json', f'builder@127.0.0.1:{remote}/'])
        payload = f'/var/tmp/apex-{build_id}/output/apex-fedora.oci.tar'
        commands = (f'bash guest/bootstrap.sh && bash guest/import-payload.sh {payload} target-image.json && '
                    f'python3 guest/nvidia-build.py {frozen["image_id"]}')
        command = f'cd {remote} && tar -xf source.tar && sudo flock -n /run/apex-build.lock bash -c {shlex.quote(commands)}'
        with (export / 'build.log').open('wb') as log:
            completed = subprocess.run(connection + [command], stdout=log, stderr=subprocess.STDOUT)
        run(connection + [f'sudo chown -R builder:builder {remote}/output 2>/dev/null || true'])
        transfer = subprocess.run(scp + ['-r', f'builder@127.0.0.1:{remote}/output', str(export)], check=False)
        execution = {'returncode': completed.returncode, 'transfer_returncode': transfer.returncode,
                     'parent_build': build_id, 'digest': frozen['digest'], 'ready_to_install': False}
        atomic_json(export / 'execution.json', execution)
        if completed.returncode or transfer.returncode:
            raise Blocked(f'NVIDIA RPM build failed; evidence retained at {export}')
        verify_report(export, frozen, manifest['files']['config/nvidia.lock.json'])
        return export
