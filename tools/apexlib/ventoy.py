"""Verified multiboot fixture preparation; privileged work stays in the builder."""
import fcntl
import json
from pathlib import Path
import shutil
import subprocess
import uuid

from .common import Blocked, ROOT, atomic_json, regular_file, run, sha256
from .signatures import verify
from .sources import download
from .vm import ssh_args


def verify_ubuntu(iso, checksums, signature, keyring, capture, locked):
    for path in (iso, checksums, signature, keyring):
        regular_file(path)
    home = capture / 'gpgv'
    home.mkdir(mode=0o700)
    result = subprocess.run(['gpgv', '--homedir', str(home), '--keyring', str(keyring.resolve()),
                             '--status-fd', '1', str(signature), str(checksums)], capture_output=True, text=True)
    (capture / 'ubuntu-signature.log').write_text(result.stdout + result.stderr)
    signers = [line.split()[2] for line in result.stdout.splitlines() if line.startswith('[GNUPG:] VALIDSIG ')]
    if result.returncode or signers != [locked['signer']]:
        raise Blocked('Ubuntu checksum signature did not match the pinned signer')
    entries = [line.split() for line in checksums.read_text().splitlines() if line.strip()]
    matches = [entry[0] for entry in entries if len(entry) == 2 and entry[1].lstrip('*') == locked['filename']]
    if matches != [locked['sha256']] or iso.stat().st_size != locked['bytes'] or sha256(iso) != locked['sha256']:
        raise Blocked('Ubuntu ISO differs from the signed pinned checksum')
    report = {'status': 'PASS', 'iso_sha256': locked['sha256'], 'signer': signers[0],
              'checksums_sha256': sha256(checksums), 'signature_sha256': sha256(signature)}
    atomic_json(capture / 'ubuntu-verification.json', report)
    return report


def prepare(directory, live_output, ubuntu, trusted_key, checksums, signature, keyring):
    with (directory / 'build.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Blocked('Wait for the active build before preparing virtual media')
        connection = ssh_args(directory)
        run_id = uuid.uuid4().hex
        capture = directory / 'ventoy-media' / run_id
        capture.mkdir(parents=True, mode=0o700)
        locked = json.loads((ROOT / 'config/ventoy-test.lock.json').read_text())
        accepted = verify(live_output, trusted_key)
        live = regular_file(live_output / 'live/Apex-Live.iso', within=directory)
        ubuntu = regular_file(ubuntu, within=directory)
        verify_ubuntu(ubuntu, checksums, signature, keyring, capture, locked['ubuntu'])
        cache = directory / 'ventoy-inputs'
        archive = cache / ('ventoy-' + locked['ventoy']['version'] + '-linux.tar.gz')
        sums = cache / 'ventoy-sha256.txt'
        download(locked['ventoy']['url'], archive, locked['ventoy']['sha256'])
        download(locked['ventoy']['checksum_url'], sums, locked['ventoy']['checksum_sha256'])
        expected_line = locked['ventoy']['sha256'] + '  ' + archive.name
        if expected_line not in sums.read_text().splitlines():
            raise Blocked('Ventoy release checksum file differs from the pinned archive')
        request = {'files': {'ventoy.tar.gz': sha256(archive), 'Apex-Live.iso': sha256(live),
                             'Ubuntu.iso': locked['ubuntu']['sha256']},
                   'ventoy_version': locked['ventoy']['version'], 'ventoy_commit': locked['ventoy']['commit'],
                   'digest': accepted['digest']}
        atomic_json(capture / 'request.json', request)
        atomic_json(capture / 'live-verification.json', accepted)
        atomic_json(capture / 'inputs.lock.json', locked)
        script = ROOT / 'guest/ventoy-fixture.py'
        atomic_json(capture / 'source.json', {'guest/ventoy-fixture.py': sha256(script),
                                             'config/ventoy-test.lock.json': sha256(ROOT / 'config/ventoy-test.lock.json')})
        remote = f'/var/tmp/apex-ventoy-{run_id}'
        run(connection + [f'mkdir -m 700 {remote}'])
        scp = ['scp', '-i', str(directory / 'builder_ed25519'), '-P', connection[4],
               '-o', 'IdentitiesOnly=yes', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
               '-o', f'UserKnownHostsFile={directory}/known_hosts']
        for source, name in ((script, 'fixture.py'), (capture / 'request.json', 'request.json'),
                             (archive, 'ventoy.tar.gz'), (live, 'Apex-Live.iso'), (ubuntu, 'Ubuntu.iso')):
            run(scp + [source, f'builder@127.0.0.1:{remote}/{name}'])
        with (capture / 'build.log').open('wb') as log:
            result = subprocess.run(connection + [f'cd {remote} && sudo flock -n /run/apex-build.lock python3 fixture.py'],
                                    stdout=log, stderr=subprocess.STDOUT)
        if result.returncode:
            atomic_json(capture / 'execution.json', {'returncode': result.returncode, 'status': 'FAIL', 'remote': remote})
            raise Blocked(f'Media preparation failed; inspect {capture}/build.log')
        run(connection + [f'sudo chown -R builder:builder {remote}/output'])
        run(scp + ['-r', f'builder@127.0.0.1:{remote}/output', str(capture)])
        report = json.loads(regular_file(capture / 'output/media.json', within=capture).read_text())
        image = regular_file(capture / 'output/ventoy.qcow2', within=capture)
        if report.get('status') != 'PASS' or report.get('request') != request or sha256(image) != report['image_sha256']:
            raise Blocked('Transferred virtual media or input identity differs')
        shutil.copyfile(sums, capture / 'ventoy-sha256.txt')
        atomic_json(capture / 'execution.json', {'status': 'PASS', 'remote': remote, 'image_sha256': report['image_sha256'],
                    'boot_acceptance': 'NOT TESTED', 'physical_usb_written': False})
        return capture
