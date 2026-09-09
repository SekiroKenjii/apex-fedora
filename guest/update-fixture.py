#!/usr/bin/python3
"""Build signed recovery fixtures only inside the isolated Fedora builder."""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import tarfile


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def policy(public_key, run_id):
    if not re.fullmatch(r'[a-f0-9]{32}', run_id):
        raise ValueError('Invalid fixture ID')
    scopes = {}
    for name, version in [('a', 'a'), ('b', 'b'), ('wrong-key', 'b'), ('unsigned', 'b')]:
        scopes[f'/var/lib/apex-update-fixture/{run_id}/{name}'] = [{
            'type': 'sigstoreSigned', 'keyData': base64.b64encode(public_key).decode(),
            'signedIdentity': {'type': 'exactReference',
                               'dockerReference': f'localhost/apex-recovery-{run_id}:{version}'}}]
    return {'default': [{'type': 'reject'}], 'transports': {'dir': scopes}}


def main():
    root = Path.cwd()
    if (os.geteuid() != 0 or Path('/etc/apex-builder').read_text().strip() != 'apex-isolated-builder-v1'
            or not re.fullmatch(r'/var/tmp/apex-update-[a-f0-9]{32}', str(root))):
        raise RuntimeError('Use an allocated directory in the isolated builder')
    if subprocess.check_output(['systemd-detect-virt', '--vm'], text=True).strip() not in {'kvm', 'qemu'}:
        raise RuntimeError('A QEMU builder is required')
    if shutil.disk_usage(root).free < 24 * 1024**3:
        raise RuntimeError('At least 24 GiB free in the builder is required')
    os.umask(0o077)
    run_id = root.name.removeprefix('apex-update-')
    output = root / 'output'
    output.mkdir(exist_ok=True)
    report = {'status': 'FAIL', 'id': run_id, 'scope': 'signed offline update fixture, not a release candidate',
              'images': {}, 'commands': [], 'automatic_fallback': 'NOT TESTED'}

    def save(path, value):
        path.write_text(json.dumps(value, indent=2) + '\n')

    def command(args, timeout=600):
        args = list(map(str, args))
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        report['commands'].append({'argv': args, 'returncode': result.returncode,
                                   'stdout': result.stdout, 'stderr': result.stderr})
        save(output / 'results.json', report)
        if result.returncode:
            raise RuntimeError(f'{args[0]} failed; see output/results.json')
        return result.stdout

    try:
        frozen = json.loads((root / 'target-image.json').read_text())
        parent = 'localhost/apex-payload:' + frozen['digest'].removeprefix('sha256:')
        raw = command(['skopeo', 'inspect', '--raw', 'containers-storage:' + parent])
        if 'sha256:' + hashlib.sha256(raw.encode()).hexdigest() != frozen['digest']:
            raise RuntimeError('Parent manifest differs from the frozen artifact')
        report['parent'] = frozen
        passphrase = root / 'passphrase'
        passphrase.write_text(secrets.token_urlsafe(32) + '\n')
        for key in ('trusted', 'wrong'):
            command(['skopeo', 'generate-sigstore-key', '--passphrase-file', passphrase,
                     '--output-prefix', root / key])
        context = root / 'context'
        context.mkdir()
        shutil.copyfile(root / 'guest/fix-grub-fragment.py', context / 'fix-grub-fragment.py')
        save(context / 'policy.json', policy((root / 'trusted.pub').read_bytes(), run_id))
        bundle = root / 'bundle'
        bundle.mkdir()
        shutil.copyfile(context / 'policy.json', bundle / 'policy.json')
        shutil.copyfile(root / 'trusted.pub', output / 'trusted.pub')
        report['public_key_sha256'] = digest(output / 'trusted.pub')
        before_policy = digest('/etc/containers/policy.json')
        baseline = command(['podman', 'run', '--rm', '--network', 'none', '--read-only', parent,
                            'rpm', '-qa', '--qf', '%{NAME}-%{EPOCHNUM}:%{VERSION}-%{RELEASE}.%{ARCH}\n'])
        baseline = '\n'.join(sorted(baseline.splitlines())) + '\n'
        (output / 'rpms.txt').write_text(baseline)
        tags = {}
        for version in ('a', 'b'):
            tag = f'localhost/apex-recovery-{run_id}:{version}'
            tags[version] = tag
            save(context / 'marker.json', {'fixture': run_id, 'version': version, 'parent': frozen['digest']})
            recipe = f'FROM {parent if version == "a" else tags["a"]}\n'
            if version == 'a':
                recipe += ('COPY policy.json /etc/containers/policy.json\n'
                           'COPY fix-grub-fragment.py /tmp/fix-grub-fragment.py\n'
                           'RUN python3 /tmp/fix-grub-fragment.py /usr/lib/bootupd/grub2-static/configs.d/08_greenboot.cfg '
                           '> /usr/share/apex/greenboot-fragment.json && rm /tmp/fix-grub-fragment.py\n')
            recipe += 'COPY marker.json /usr/share/apex/recovery-fixture.json\n'
            (context / 'Containerfile').write_text(recipe)
            shutil.copyfile(context / 'Containerfile', output / f'Containerfile.{version}')
            command(['podman', 'build', '--network=none', '--pull=never', '--layers=false', '-t', tag, context])
            rpms = command(['podman', 'run', '--rm', '--network', 'none', '--read-only', tag,
                            'rpm', '-qa', '--qf', '%{NAME}-%{EPOCHNUM}:%{VERSION}-%{RELEASE}.%{ARCH}\n'])
            if '\n'.join(sorted(rpms.splitlines())) + '\n' != baseline:
                raise RuntimeError('Fixture changed the RPM inventory')
            command(['podman', 'run', '--rm', '--network', 'none', tag, 'bootc', 'container', 'lint', '--fatal-warnings'])
            signing_policy = root / 'signing-policy.json'
            save(signing_policy, {'default': [{'type': 'reject'}], 'transports': {'containers-storage': {
                '[overlay@/var/lib/containers/storage]' + tag: [{'type': 'insecureAcceptAnything'}]}}})
            command(['skopeo', '--policy', signing_policy, 'copy', '--preserve-digests',
                     '--sign-by-sigstore-private-key', root / 'trusted.private',
                     '--sign-passphrase-file', passphrase, '--sign-identity', tag,
                     'containers-storage:' + tag, 'dir:' + str(bundle / version)])
            manifest = bundle / version / 'manifest.json'
            report['images'][version] = {'digest': 'sha256:' + digest(manifest),
                                         'config': json.loads(manifest.read_text())['config']['digest'], 'identity': tag}
            shutil.copyfile(manifest, output / f'manifest-{version}.json')
        # Share only immutable, content-addressed blobs. Signatures/manifests remain separate.
        for blob in (bundle / 'b').iterdir():
            peer = bundle / 'a' / blob.name
            if re.fullmatch('[a-f0-9]{64}', blob.name) and peer.is_file() and digest(blob) == digest(peer):
                blob.unlink()
                os.link(peer, blob)
        for case in ('unsigned', 'untrusted'):
            shutil.copytree(bundle / 'b', bundle / case, copy_function=os.link)
        for signature in (bundle / 'unsigned').glob('signature-*'):
            signature.unlink()
        command(['skopeo', '--policy', signing_policy, 'copy', '--preserve-digests',
                 '--sign-by-sigstore-private-key', root / 'wrong.private',
                 '--sign-passphrase-file', passphrase, '--sign-identity', tags['b'],
                 'containers-storage:' + tags['b'], 'dir:' + str(root / 'wrong-signed')])
        shutil.copytree(bundle / 'b', bundle / 'wrong-key', copy_function=os.link)
        for signature in (bundle / 'wrong-key').glob('signature-*'):
            signature.unlink()
        for signature in (root / 'wrong-signed').glob('signature-*'):
            shutil.copyfile(signature, bundle / 'wrong-key' / signature.name)
        report['files'] = {str(p.relative_to(bundle)): digest(p) for p in sorted(bundle.rglob('*')) if p.is_file()}
        save(bundle / 'fixture.json', {k: report[k] for k in ('id', 'parent', 'images', 'files', 'public_key_sha256')})
        with tarfile.open(output / 'payloads.tar', 'w') as archive:
            archive.add(bundle, arcname=run_id)
        report['archive_sha256'] = digest(output / 'payloads.tar')
        if digest('/etc/containers/policy.json') != before_policy:
            raise RuntimeError('Builder policy changed')
        report['unchanged_builder_policy_sha256'] = before_policy
        report['status'] = 'PASS'
    finally:
        save(output / 'results.json', report)


if __name__ == '__main__':
    main()
