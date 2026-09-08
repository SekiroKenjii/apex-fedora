#!/usr/bin/python3
"""Add final SELinux labeling to image-builder's generic installer filesystem."""
import copy
import json
from pathlib import Path
import re
import sys


def prepare(manifest, buildroot, embedded_payload=None):
    result = copy.deepcopy(manifest)
    if result.get('version') != '2':
        raise ValueError('Expected an osbuild version 2 manifest')
    pipelines = result.get('pipelines', [])
    trees = [p for p in pipelines if p.get('name') == 'os-tree']
    if len(trees) != 1 or not any(p.get('name') == 'bootiso' for p in pipelines):
        raise ValueError('Expected the generic ISO os-tree and bootiso pipelines')
    builders = [p for p in pipelines if p.get('name') == 'build']
    if len(builders) != 1 or not builders[0].get('stages') or builders[0]['stages'][0].get('type') != 'org.osbuild.container-deploy':
        raise ValueError('Unexpected generic ISO build pipeline')
    if not isinstance(buildroot, list) or len(buildroot) != 1:
        raise ValueError('Expected one inspected tools buildroot')
    ident = buildroot[0].get('Id', '').removeprefix('sha256:')
    tag = f'localhost/apex-artifact-builder:{ident}'
    if not re.fullmatch('[a-f0-9]{64}', ident) or tag not in buildroot[0].get('RepoTags', []):
        raise ValueError('Tools buildroot must have an immutable local tag')
    images = builders[0]['stages'][0].get('inputs', {}).get('images', {})
    if images.get('type') != 'org.osbuild.containers-storage' or images.get('origin') != 'org.osbuild.source' or len(images.get('references', {})) != 1:
        raise ValueError('Unexpected tools buildroot image input')
    images['references'] = {f'sha256:{ident}': {'name': tag}}
    result['sources']['org.osbuild.containers-storage']['items'][f'sha256:{ident}'] = {}
    stages = trees[0].get('stages', [])
    if not stages or stages[0].get('type') != 'org.osbuild.container-deploy':
        raise ValueError('Unexpected installer filesystem source')
    serialized = json.dumps(result)
    if 'enforcing=0' in serialized or 'selinux=0' in serialized or 'inst.ks=' in serialized:
        raise ValueError('Installer manifest contains disabled enforcement or an automatic kickstart')
    if 'enforcing=1' not in serialized:
        raise ValueError('Installer manifest lacks explicit enforcement')
    if any(stage.get('type') == 'org.osbuild.selinux' for stage in stages):
        raise ValueError('Upstream installer labeling changed; review the existing stage')
    if embedded_payload is not None:
        digest = embedded_payload.get('digest', '')
        image = embedded_payload.get('image_id', '')
        if not re.fullmatch('sha256:[a-f0-9]{64}', digest) or not re.fullmatch('sha256:[a-f0-9]{64}', image):
            raise ValueError('Invalid embedded payload identity')
        payload_stages = [s for s in stages if s.get('type') == 'org.osbuild.skopeo']
        if len(payload_stages) != 1:
            raise ValueError('Expected exactly one upstream payload-copy stage')
        stage = payload_stages[0]
        expected = {'type': 'org.osbuild.containers-storage', 'origin': 'org.osbuild.source',
                    'references': {image: {'name': 'localhost/apex-payload:' + digest[7:]}}}
        if stage.get('inputs') != {'images': expected} or stage.get('options') != {'destination': {'type': 'containers-storage'}}:
            raise ValueError('Upstream payload-copy contract changed')
        # The derived image already contains signed dir: blobs. Recopying an unpacked
        # store would change their representation and invalidate the signature.
        stages.remove(stage)
    stages.append({'type': 'org.osbuild.selinux', 'options': {
        'file_contexts': 'etc/selinux/targeted/contexts/files/file_contexts',
        'exclude_paths': ['/sysroot']}})
    return result


if __name__ == '__main__':
    source, destination, buildroot, payload = map(Path, sys.argv[1:])
    destination.write_text(json.dumps(prepare(json.loads(source.read_text()), json.loads(buildroot.read_text()), json.loads(payload.read_text())), indent=2) + '\n')
