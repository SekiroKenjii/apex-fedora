import json

import pytest
from apexlib import sources
from apexlib.common import ROOT, Blocked


def locked():
    return json.loads((ROOT / 'config/sources.lock.json').read_text())


def test_checked_in_source_lock_is_valid():
    sources.validate_lock(locked())


@pytest.mark.parametrize('fault', [
    'schema', 'missing-image', 'mutable-image', 'mismatched-image', 'missing-digest',
    'empty-sources', 'missing-checksum', 'short-checksum', 'http', 'branch',
    'path', 'duplicate', 'bad-entry',
])
def test_invalid_lock_is_rejected_before_download(tmp_path, monkeypatch, fault):
    lock = locked()
    source = lock['sources']['shadcn-gnome']
    if fault == 'schema':
        lock['schema'] = True
    elif fault == 'missing-image':
        lock.pop('base')
    elif fault == 'mutable-image':
        lock['image_builder']['reference'] = 'ghcr.io/osbuild/image-builder-cli:latest'
    elif fault == 'mismatched-image':
        lock['image_builder']['digest'] = 'sha256:' + '0' * 64
    elif fault == 'missing-digest':
        lock['base'].pop('digest')
    elif fault == 'empty-sources':
        lock['sources'] = {}
    elif fault == 'missing-checksum':
        source.pop('sha256')
    elif fault == 'short-checksum':
        source['sha256'] = 'abcd'
    elif fault == 'http':
        source['url'] = source['url'].replace('https:', 'http:')
    elif fault == 'branch':
        source['commit'] = 'main'
    elif fault == 'path':
        source['filename'] = '../outside.tar.gz'
    elif fault == 'duplicate':
        source['filename'] = 'collision.tar.gz'
        lock['sources']['macos-genie']['filename'] = 'collision.tar.gz'
    else:
        lock['sources']['shadcn-gnome'] = []
    project = tmp_path / 'project'
    (project / 'config').mkdir(parents=True)
    (project / 'config/sources.lock.json').write_text(json.dumps(lock))
    monkeypatch.setattr(sources, 'ROOT', project)
    monkeypatch.setattr(sources, 'download', lambda *args: pytest.fail('Network attempted with invalid lock'))
    with pytest.raises(Blocked):
        sources.acquire(tmp_path / 'runtime')
    assert not (tmp_path / 'runtime').exists()


@pytest.mark.parametrize('fault', ['missing', 'malformed', 'symlink'])
def test_lock_cannot_be_silently_recreated(tmp_path, monkeypatch, fault):
    project = tmp_path / 'project'
    (project / 'config').mkdir(parents=True)
    pinned = project / 'config/sources.lock.json'
    if fault == 'malformed':
        pinned.write_text('{unfinished')
    elif fault == 'symlink':
        other = tmp_path / 'outside.json'
        other.write_text(json.dumps(locked()))
        pinned.symlink_to(other)
    monkeypatch.setattr(sources, 'ROOT', project)
    monkeypatch.setattr(sources, 'download', lambda *args: pytest.fail('Network attempted without a reviewed lock'))
    with pytest.raises(Blocked):
        sources.acquire(tmp_path / 'runtime')
    assert not (tmp_path / 'runtime').exists()


def test_acquisition_preserves_the_reviewed_lock(tmp_path, monkeypatch):
    expected = locked()
    calls = []
    monkeypatch.setattr(sources, 'download', lambda *args: calls.append(args))
    result = sources.acquire(tmp_path)
    assert result == expected
    assert len(calls) == len(expected['sources'])
    assert all(len(args[2]) == 64 for args in calls)
    assert json.loads((tmp_path / 'sources.lock.json').read_text()) == expected
