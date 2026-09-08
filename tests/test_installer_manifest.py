import importlib.util
import pytest
from apexlib.common import ROOT

spec = importlib.util.spec_from_file_location('installer_manifest', ROOT / 'guest/label-installer-manifest.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def fixture():
    return {'version': '2', 'pipelines': [
        {'name': 'build', 'stages': [{'type': 'org.osbuild.container-deploy', 'inputs': {'images': {
            'type': 'org.osbuild.containers-storage', 'origin': 'org.osbuild.source',
            'references': {'sha256:' + '1' * 64: {'name': 'localhost/installer'}}}}}]},
        {'name': 'os-tree', 'stages': [{'type': 'org.osbuild.container-deploy'}]},
        {'name': 'bootiso', 'stages': [{'options': {'kernel': 'enforcing=1'}}]}],
        'sources': {'org.osbuild.containers-storage': {'items': {'sha256:' + '1' * 64: {}}}}}


def buildroot():
    return [{'Id': '2' * 64, 'RepoTags': ['localhost/apex-artifact-builder:' + '2' * 64]}]


def test_labels_installer_tree_after_payload_without_changing_input():
    source = fixture()
    result = module.prepare(source, buildroot())
    assert len(source['pipelines'][1]['stages']) == 1
    assert result['pipelines'][1]['stages'][-1]['type'] == 'org.osbuild.selinux'
    assert 'sha256:' + '2' * 64 in result['pipelines'][0]['stages'][0]['inputs']['images']['references']
    assert source['pipelines'][0]['stages'][0]['inputs']['images']['references'] != result['pipelines'][0]['stages'][0]['inputs']['images']['references']


@pytest.mark.parametrize('unsafe', ['enforcing=0', 'selinux=0', 'inst.ks=anything'])
def test_rejects_unsafe_boot_contract(unsafe):
    source = fixture()
    source['pipelines'][2]['stages'][0]['options']['kernel'] += ' ' + unsafe
    with pytest.raises(ValueError):
        module.prepare(source, buildroot())


def test_requires_review_when_upstream_adds_labeling():
    with pytest.raises(ValueError, match='Upstream'):
        module.prepare(module.prepare(fixture(), buildroot()), buildroot())


def test_rejects_mutable_or_mismatched_buildroot():
    with pytest.raises(ValueError, match='immutable'):
        module.prepare(fixture(), [{'Id': '2' * 64, 'RepoTags': ['localhost/apex-artifact-builder:trial']}])
