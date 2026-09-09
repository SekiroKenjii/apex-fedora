from __future__ import annotations

import io
import fcntl
import json
from pathlib import Path
import re
import shlex
import subprocess
import tarfile
import uuid

from .common import ROOT, Blocked, atomic_json, regular_file, run, sha256
from .gitguard import inspect_blob
from .sources import acquire
from .vm import ssh_args

SOURCE_PATHS = ("Containerfile", "config", "guest", "rpms", "system_files", "live", "tools")


def fingerprint_tests(directory: Path, build_id: str):
    if not re.fullmatch(r'[a-f0-9]{32}', build_id):
        raise Blocked('Fingerprint tests require a completed image build ID')
    previous = directory / 'exports' / build_id
    result = json.loads(regular_file(previous / 'result.json', within=directory).read_text())
    if result.get('status') != 'PASS' or result.get('kind') != 'image':
        raise Blocked('Fingerprint tests require a completed image build')
    frozen = json.loads(regular_file(previous / 'output/image.json', within=directory).read_text())
    manifest = regular_file(previous / 'output/manifest.json', within=directory)
    if (frozen['digest'] != 'sha256:' + sha256(manifest)
            or not re.fullmatch(r'sha256:[a-f0-9]{64}', frozen['image_id'])
            or json.loads(manifest.read_text()).get('config', {}).get('digest') != frozen['image_id']):
        raise Blocked('Frozen image identity mismatch')
    with (directory / 'build.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Blocked('Wait for the active build before testing fingerprint packages')
        connection = ssh_args(directory)
        run_id = uuid.uuid4().hex
        export = directory / 'fingerprint-tests' / run_id
        export.mkdir(parents=True, mode=0o700)
        bundle = export / 'source.tar'
        atomic_json(export / 'source-manifest.json', export_source(bundle))
        atomic_json(export / 'target-image.json', frozen)
        remote = f'/var/tmp/apex-fingerprint-{run_id}'
        run(connection + [f'mkdir -m 700 {remote}'])
        scp = ['scp', '-i', str(directory / 'builder_ed25519'), '-P', connection[4],
               '-o', 'IdentitiesOnly=yes', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
               '-o', f'UserKnownHostsFile={directory}/known_hosts']
        run(scp + [bundle, export / 'target-image.json', f'builder@127.0.0.1:{remote}/'])
        payload = f'/var/tmp/apex-{build_id}/output/apex-{frozen["profile"]}.oci.tar'
        if frozen['profile'] not in {'fedora', 'cachyos'}:
            raise Blocked('Unknown frozen image profile')
        commands = (f'bash guest/import-payload.sh {payload} target-image.json && '
                    f'bash guest/fingerprint-tests.sh {frozen["image_id"]}')
        command = f'cd {remote} && tar -xf source.tar && sudo flock -n /run/apex-build.lock bash -c {shlex.quote(commands)}'
        with (export / 'test.log').open('wb') as log:
            completed = subprocess.run(connection + [command], stdout=log, stderr=subprocess.STDOUT)
        transfer = subprocess.run(scp + ['-r', f'builder@127.0.0.1:{remote}/output', str(export)], check=False)
        atomic_json(export / 'execution.json', {'returncode': completed.returncode,
                    'transfer_returncode': transfer.returncode, 'digest': frozen['digest'],
                    'parent_build': build_id, 'hardware_acceptance': 'NOT TESTED'})
        if completed.returncode or transfer.returncode:
            raise Blocked(f'Fingerprint fixture did not pass; retained evidence: {export}')
        report = json.loads(regular_file(export / 'output/fingerprint/results.json', within=export).read_text())
        if report.get('status') != 'PASS' or report.get('tests_run') != 8 or report.get('skipped'):
            raise Blocked('Fingerprint fixtures did not complete every case')
        return export


def installer_trust(directory: Path):
    with (directory / 'build.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Blocked('Wait for the active build before running signature fixtures')
        connection = ssh_args(directory)
        run_id = uuid.uuid4().hex
        export = directory / 'signature-policy-tests' / run_id
        export.mkdir(parents=True, mode=0o700)
        remote = f'/var/tmp/apex-trust-{run_id}'
        script = ROOT / 'guest/test-installer-trust.py'
        run(connection + [f'mkdir -m 700 {remote}'])
        scp = ['scp', '-i', str(directory / 'builder_ed25519'), '-P', connection[4],
               '-o', 'IdentitiesOnly=yes', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
               '-o', f'UserKnownHostsFile={directory}/known_hosts']
        run(scp + [script, f'builder@127.0.0.1:{remote}/test.py'])
        dependency = ROOT / 'guest/installer-preflight.py'
        run(scp + [dependency, f'builder@127.0.0.1:{remote}/installer-preflight.py'])
        atomic_json(export / 'source.json', {'path': 'guest/test-installer-trust.py', 'sha256': sha256(script),
                                           'dependencies': {'guest/installer-preflight.py': sha256(dependency)}})
        with (export / 'test.log').open('wb') as log:
            result = subprocess.run(connection + [f'sudo flock -n /run/apex-build.lock python3 {remote}/test.py {remote}/output'], stdout=log, stderr=subprocess.STDOUT)
        run(connection + [f'sudo chown -R builder:builder {remote}/output 2>/dev/null || true'])
        # Copy only the report and public keys. Signing keys and passphrases remain in the VM.
        names = ('results.json', 'trusted.pub', 'wrong.pub')
        transfer = subprocess.run(scp + [*[f'builder@127.0.0.1:{remote}/output/{name}' for name in names], str(export)], check=False)
        if result.returncode or transfer.returncode:
            raise Blocked(f'Signature fixture failed; inspect {export}/test.log')
        report = json.loads(regular_file(export / 'results.json', within=export).read_text())
        expected = {'signed-roundtrip', 'same-store-preflight', 'wrong-key', 'wrong-identity',
                    'unsigned', 'tampered-signature', 'tampered-manifest', 'unexpected-source'}
        if (report.get('status') != 'PASS' or report.get('cases') != dict.fromkeys(expected, 'PASS')
                or report.get('proxy_cases') != dict.fromkeys(expected, 'PASS')):
            raise Blocked('Signature fixtures did not complete every required case')
        for name in ('trusted', 'wrong'):
            if sha256(regular_file(export / f'{name}.pub', within=export)) != report['public_key_sha256'][name]:
                raise Blocked('Transferred fixture public key checksum mismatch')
        return export


def installer_fixtures(directory: Path):
    with (directory / 'build.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Blocked('Wait for the active build before creating installer fixtures')
        connection = ssh_args(directory)
        run_id = uuid.uuid4().hex
        export = directory / 'installer-fixtures' / run_id
        export.mkdir(parents=True, mode=0o700)
        remote = f'/var/tmp/apex-fixtures-{run_id}'
        script = ROOT / 'guest/installer-fixtures.py'
        run(connection + [f'mkdir -m 700 {remote}'])
        scp = ['scp', '-i', str(directory / 'builder_ed25519'), '-P', connection[4],
               '-o', 'IdentitiesOnly=yes', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
               '-o', f'UserKnownHostsFile={directory}/known_hosts']
        run(scp + [script, f'builder@127.0.0.1:{remote}/fixtures.py'])
        atomic_json(export / 'source.json', {'path': 'guest/installer-fixtures.py', 'sha256': sha256(script)})
        with (export / 'build.log').open('wb') as log:
            result = subprocess.run(connection + [f'cd {remote} && sudo flock -n /run/apex-build.lock python3 fixtures.py'], stdout=log, stderr=subprocess.STDOUT)
        run(connection + [f'sudo chown -R builder:builder {remote}/output 2>/dev/null || true'])
        transfer = subprocess.run(scp + ['-r', f'builder@127.0.0.1:{remote}/output', str(export)], check=False)
        atomic_json(export / 'result.json', {'status': 'PASS' if result.returncode == transfer.returncode == 0 else 'FAIL'})
        if result.returncode or transfer.returncode:
            raise Blocked(f'Fixture preparation failed; inspect {export}/build.log')
        report = json.loads((export / 'output/fixtures.json').read_text())
        for name, expected in report['sha256'].items():
            if name not in {'target.qcow2', 'other.qcow2'} or sha256(regular_file(export / 'output' / name, within=export)) != expected:
                raise Blocked('Transferred fixture checksum mismatch')
        return export


def export_source(destination: Path) -> dict:
    files = {}
    with tarfile.open(destination, "w") as archive:
        for entry in SOURCE_PATHS:
            root = ROOT / entry
            if not root.exists():
                continue
            candidates = sorted(root.rglob("*")) if root.is_dir() else [root]
            for path in candidates:
                if path.is_dir() and not path.is_symlink():
                    continue
                if path.is_symlink() or not path.is_file():
                    raise Blocked(f"Build input is not a regular file: {path}")
                name = str(path.relative_to(ROOT))
                if "__pycache__" in path.parts:
                    continue
                data = path.read_bytes()
                inspect_blob(name, "100644", data)
                info = tarfile.TarInfo(name)
                info.size = len(data)
                info.mode = 0o755 if path.suffix == ".sh" else 0o644
                info.mtime = 0
                archive.addfile(info, io.BytesIO(data))
                files[name] = sha256(path)
    return {"archive_sha256": sha256(destination), "files": files}


def execute(directory: Path, profile: str, kind: str = "image", build_id: str | None = None, *, test_access: bool = False):
    with (directory / "build.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Blocked("Another Apex build or artifact operation is running")
        return _execute(directory, profile, kind, build_id, test_access)


def _execute(directory: Path, profile: str, kind: str, build_id: str | None, test_access: bool):
    if profile not in {"fedora", "cachyos"} or kind not in {"image", "qcow2", "installer", "live"}:
        raise Blocked("Unknown build profile or artifact type")
    if test_access and kind != 'qcow2':
        raise Blocked('Test credentials are restricted to private QCOW2 fixtures')
    frozen = None
    if kind != "image":
        if not build_id or not re.fullmatch(r"[a-f0-9]{32}", build_id):
            raise Blocked("Artifact creation needs a completed --build ID")
        previous = directory / "exports" / build_id
        result = json.loads(regular_file(previous / "result.json", within=directory).read_text())
        if result["status"] != "PASS" or result["kind"] != "image":
            raise Blocked("The selected image build did not complete")
        frozen = json.loads(regular_file(previous / "output/image.json", within=directory).read_text())
        manifest = regular_file(previous / "output/manifest.json", within=directory)
        if frozen["digest"] != "sha256:" + sha256(manifest):
            raise Blocked("The frozen image manifest changed")
        if not re.fullmatch(r"sha256:[a-f0-9]{64}", frozen["image_id"]):
            raise Blocked("Invalid frozen image ID")
        if json.loads(manifest.read_text()).get("config", {}).get("digest") != frozen["image_id"]:
            raise Blocked("The frozen image ID does not match its OCI manifest")
        profile = frozen["profile"]
    elif profile == "cachyos":
        raise Blocked("CachyOS needs a reviewed kernel source/RPM lock and matching NVIDIA modules first")
    connection = ssh_args(directory)
    run(connection + ["test -f /etc/apex-builder && systemd-detect-virt --quiet --vm"])
    acquire(directory)
    run_id = uuid.uuid4().hex
    export = directory / "exports" / run_id
    export.mkdir(parents=True)
    bundle = export / "source.tar"
    manifest = export_source(bundle)
    atomic_json(export / "source-manifest.json", manifest)
    remote = f"/var/tmp/apex-{run_id}"
    run(connection + [f"mkdir -m 700 {remote}"])
    # SCP handles file transfer; the guest command never receives an arbitrary host path.
    scp = ["scp", "-i", str(directory / "builder_ed25519"), "-P", connection[4], "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes", "-o", f"UserKnownHostsFile={directory}/known_hosts"]
    run(scp + [bundle, f"builder@127.0.0.1:{remote}/source.tar"])
    if frozen:
        target = "disk-artifact.sh" if kind in {"qcow2", "installer"} else "live-artifact.sh"
        image_id = frozen["image_id"]
        atomic_json(export / "target-image.json", frozen)
        run(scp + [export / "target-image.json", f"builder@127.0.0.1:{remote}/target-image.json"])
        payload = f"/var/tmp/apex-{build_id}/output/apex-{profile}.oci.tar"
        archive_arg = f' {payload}' if kind == 'installer' else ''
        build_command = f"bash guest/import-payload.sh {payload} target-image.json && bash guest/{target} {kind} {image_id}{archive_arg} && python3 guest/sign-artifacts.py output target-image.json"
        if test_access:
            from .testaccess import create
            blueprint = create(export)
            run(scp + [blueprint, f"builder@127.0.0.1:{remote}/test-blueprint.toml"])
    else:
        build_command = f"bash guest/build.sh {profile} image"
    command = f"cd {remote} && tar -xf source.tar && sudo flock -n /run/apex-build.lock bash -c {shlex.quote('bash guest/bootstrap.sh && ' + build_command)}"
    with (export / "build.log").open("wb") as log:
        proc = subprocess.Popen(connection + [command], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        for line in proc.stdout:
            log.write(line)
            log.flush()
            print(line.decode(errors="replace"), end="", flush=True)
        code = proc.wait()
    # Copy logs even when a build fails. Never turn a partial artifact into a candidate.
    run(connection + [f"sudo chown -R builder:builder {remote}/output 2>/dev/null || true"])
    transfer = subprocess.run(scp + ["-r", f"builder@127.0.0.1:{remote}/output", str(export)], check=False)
    code = code or transfer.returncode
    atomic_json(export / "result.json", {"status": "PASS" if code == 0 else "FAIL", "kind": kind, "profile": profile, "source_sha256": manifest["archive_sha256"], "remote": remote, "parent_build": build_id, "test_access": test_access})
    if code:
        raise Blocked(f"Guest build failed; retained log: {export}/build.log")
    print(f"Build output retained at {export}")
