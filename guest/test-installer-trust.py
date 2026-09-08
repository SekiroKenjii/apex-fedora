#!/usr/bin/python3
"""Exercise real containers/image signature checks with disposable VM fixtures."""
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import tempfile


def main(export=None):
    marker = Path('/etc/apex-builder')
    if os.geteuid() != 0 or not marker.is_file() or marker.read_text().strip() != 'apex-isolated-builder-v1':
        raise RuntimeError('Run only in the isolated Fedora builder')
    virtual = subprocess.run(['systemd-detect-virt', '--vm'], capture_output=True, text=True, timeout=5)
    if virtual.returncode or virtual.stdout.strip() not in {'kvm', 'qemu'}:
        raise RuntimeError('QEMU builder virtualization is required')
    os.umask(0o077)
    if export is not None:
        export = Path(export)
        if not re.fullmatch('/var/tmp/apex-trust-[a-f0-9]{32}/output', str(export)) or export.resolve() != export or not export.parent.is_dir():
            raise RuntimeError('Use the private output directory allocated by the host runner')
    root = Path(tempfile.mkdtemp(prefix='apex-trust-', dir='/var/tmp'))
    output = export or root / 'output'
    output.mkdir()
    report = {'status': 'FAIL', 'scope': 'synthetic image in builder VM, not Apex installer acceptance',
              'work_directory': str(root), 'cases': {}, 'commands': []}

    def command(args, *, check=True):
        args = list(map(str, args))
        result = subprocess.run(args, capture_output=True, text=True, timeout=120)
        report['commands'].append({'argv': args, 'returncode': result.returncode,
                                   'stdout': result.stdout, 'stderr': result.stderr})
        if check and result.returncode:
            raise RuntimeError(f'Fixture command failed: {args[0]}; retained {output}/results.json')
        return result

    def save(path, value):
        path.write_text(json.dumps(value, indent=2) + '\n')

    try:
        system_policy = Path('/etc/containers/policy.json')
        policy_before = hashlib.sha256(system_policy.read_bytes()).hexdigest()
        report['skopeo_version'] = command(['skopeo', '--version']).stdout.strip()
        store = command(['podman', 'info', '--format', '{{.Store.GraphDriverName}} {{.Store.GraphRoot}}']).stdout.split()
        if store != ['overlay', '/var/lib/containers/storage']:
            raise RuntimeError('Review the fixture policy for this container store')
        tag = 'localhost/apex-trust-fixture:' + root.name.removeprefix('apex-trust-')
        verified_tag = tag.replace('fixture:', 'verified:')
        store_scope = '[overlay@/var/lib/containers/storage]'
        context = root / 'context'
        context.mkdir()
        (context / 'Containerfile').write_text('FROM scratch\nCOPY payload.txt /payload.txt\n')
        (context / 'payload.txt').write_text('Apex signature fixture; not an operating system.\n')
        command(['podman', 'build', '--pull=never', '--layers=false', '-t', tag, context])
        passphrase = root / 'passphrase'
        passphrase.write_text(secrets.token_urlsafe(32) + '\n')
        for name in ('trusted', 'wrong'):
            command(['skopeo', 'generate-sigstore-key', '--passphrase-file', passphrase,
                     '--output-prefix', root / name])
            shutil.copyfile(root / f'{name}.pub', output / f'{name}.pub')
        report['public_key_sha256'] = {name: hashlib.sha256((output / f'{name}.pub').read_bytes()).hexdigest()
                                       for name in ('trusted', 'wrong')}

        # Bootstrap signing accepts only this newly built synthetic image. Neither
        # the builder's system policy nor the Apex image policy is changed.
        signing = root / 'signing-policy.json'
        save(signing, {'default': [{'type': 'reject'}], 'transports': {'containers-storage': {
            store_scope + tag: [{'type': 'insecureAcceptAnything'}]}}})
        signed = root / 'signed'
        command(['skopeo', '--policy', signing, 'copy', '--preserve-digests',
                 '--sign-by-sigstore-private-key', root / 'trusted.private',
                 '--sign-passphrase-file', passphrase, '--sign-identity', tag,
                 'containers-storage:' + tag, 'dir:' + str(signed)])

        def requirement(key='trusted', identity=tag):
            return [{'type': 'sigstoreSigned', 'keyPath': str(root / f'{key}.pub'),
                     'signedIdentity': {'type': 'exactReference', 'dockerReference': identity}}]

        def policy(path, source_directory, *, key='trusted', identity=tag):
            save(path, {'default': [{'type': 'reject'}], 'transports': {
                'dir': {str(source_directory): requirement(key, identity)},
                'containers-storage': {store_scope + verified_tag: requirement(key, identity)}}})

        trusted_policy = root / 'trusted-policy.json'
        policy(trusted_policy, signed)
        command(['skopeo', '--policy', trusted_policy, 'copy', '--preserve-digests',
                 'dir:' + str(signed), 'containers-storage:' + verified_tag])
        command(['skopeo', '--policy', trusted_policy, 'copy', '--preserve-digests',
                 'containers-storage:' + verified_tag, 'dir:' + str(root / 'verified-copy')])
        digest = hashlib.sha256((signed / 'manifest.json').read_bytes()).hexdigest()
        assert hashlib.sha256((root / 'verified-copy/manifest.json').read_bytes()).hexdigest() == digest
        report['manifest_digest'] = 'sha256:' + digest
        report['cases']['signed-roundtrip'] = 'PASS'
        command(['skopeo', '--policy', trusted_policy, 'copy', '--preserve-digests',
                 'containers-storage:' + verified_tag,
                 'containers-storage:' + tag.replace('fixture:', 'preflight:')])
        report['cases']['same-store-preflight'] = 'PASS'

        def reject(name, source, selected_policy, pattern):
            result = command(['skopeo', '--policy', selected_policy, 'copy', '--preserve-digests',
                              source, 'dir:' + str(root / f'rejected-{name}')], check=False)
            if result.returncode == 0 or not re.search(pattern, result.stderr, re.IGNORECASE):
                raise RuntimeError(f'{name} did not produce the expected policy rejection')
            report['cases'][name] = 'PASS'

        wrong_policy = root / 'wrong-policy.json'
        policy(wrong_policy, signed, key='wrong')
        reject('wrong-key', 'containers-storage:' + verified_tag, wrong_policy, 'signature')
        wrong_identity = root / 'wrong-identity-policy.json'
        policy(wrong_identity, signed, identity='localhost/apex-unexpected:fixture')
        reject('wrong-identity', 'containers-storage:' + verified_tag, wrong_identity, 'identity|reference|signature')

        signature_files = sorted(p.name for p in signed.iterdir() if p.name.startswith('signature-'))
        if not signature_files:
            raise RuntimeError('Signed fixture has no signature files')
        for name in ('unsigned', 'tampered-signature', 'tampered-manifest', 'unexpected-source'):
            destination = root / name
            shutil.copytree(signed, destination)
            selected_policy = root / f'{name}-policy.json'
            policy(selected_policy, destination if name != 'unexpected-source' else signed)
            if name == 'unsigned':
                for filename in signature_files:
                    (destination / filename).unlink()
            elif name == 'tampered-signature':
                (destination / signature_files[0]).write_bytes(b'Invalid synthetic signature\n')
            elif name == 'tampered-manifest':
                manifest = json.loads((destination / 'manifest.json').read_text())
                manifest.setdefault('annotations', {})['apex.test.tampered'] = 'true'
                save(destination / 'manifest.json', manifest)
            reject(name, 'dir:' + str(destination), selected_policy,
                   'signature|rejected by policy|digest.*match')
        assert hashlib.sha256(system_policy.read_bytes()).hexdigest() == policy_before
        report['unchanged_system_policy_sha256'] = policy_before
        report['status'] = 'PASS'
    finally:
        save(output / 'results.json', report)
        print(output, flush=True)


if __name__ == '__main__':
    if len(sys.argv) > 2:
        sys.exit('Usage: test-installer-trust.py [PRIVATE_OUTPUT_DIRECTORY]')
    main(sys.argv[1] if len(sys.argv) == 2 else None)
