import importlib.util
from pathlib import Path

import pytest

from apexlib.common import Blocked


def module():
    spec = importlib.util.spec_from_file_location('compact', Path(__file__).resolve().parents[1] / 'tools/compact-builder.py')
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


@pytest.mark.parametrize('change', [{'snapshots': [{}]}, {'dirty-flag': True},
                                  {'format-specific': {'data': {'bitmaps': [{}]}}},
                                  {'format-specific': {'data': {'corrupt': True}}}])
def test_compaction_refuses_metadata_that_would_be_lost(change):
    with pytest.raises(Blocked):
        module().validate_info([{'format': 'qcow2'} | change])


def test_compaction_accepts_a_clean_chain():
    module().validate_info([{'format': 'qcow2'}, {'format': 'qcow2'}])


def test_compaction_refuses_a_non_qcow2_source():
    with pytest.raises(Blocked):
        module().validate_info([{'format': 'raw'}])


def retained_report(source, target):
    return {'source': str(source), 'replacement': 'NOT PERFORMED',
            'error': 'Validated copy does not save enough space; original retained',
            'source_sha256': 'a' * 64, 'compressed_sha256': 'b' * 64,
            'commands': [{'argv': ['qemu-img', 'compare', '-f', 'qcow2', '-F', 'qcow2', str(source), str(target)],
                          'returncode': 0}]}


def test_retained_copy_requires_exact_successful_comparison():
    source, target = Path('/runtime/builder.qcow2'), Path('/runtime/retained.qcow2')
    module().validate_retained(retained_report(source, target), source, target)


@pytest.mark.parametrize('change', [{'replacement': 'COMPLETE'}, {'source': '/different.qcow2'},
                                  {'error': 'Conversion failed'}, {'source_sha256': ''},
                                  {'compressed_sha256': 'x' * 64}, {'commands': []},
                                  {'commands': [{'argv': ['qemu-img', 'compare'], 'returncode': 1}]}])
def test_ineligible_retained_copy_is_rejected(change):
    source, target = Path('/runtime/builder.qcow2'), Path('/runtime/retained.qcow2')
    with pytest.raises(Blocked):
        module().validate_retained(retained_report(source, target) | change, source, target)


def test_storage_refusal_still_uses_configured_threshold(tmp_path, monkeypatch):
    from types import SimpleNamespace
    tool = module()
    source = tmp_path / 'builder.qcow2'
    source.write_bytes(b'test')
    monkeypatch.setattr(tool.shutil, 'disk_usage', lambda _: SimpleNamespace(free=174 * 1024**3))
    monkeypatch.setattr(tool, 'config', lambda: {'builder': {'minimum_free_gib': 180}})
    with pytest.raises(Blocked, match='threshold'):
        tool.projected_free(tmp_path, source)


@pytest.fixture
def tiny_retained_copy(tmp_path, monkeypatch):
    import json
    import shutil
    import subprocess
    from apexlib.common import sha256
    if not shutil.which('qemu-img'):
        pytest.skip('qemu-img is required for regular-file compaction tests')
    tool = module()
    source = tmp_path / 'builder.qcow2'
    run_id = 'a' * 32
    previous = tmp_path / 'compactions' / run_id
    previous.mkdir(parents=True)
    target = previous / 'builder-compressed.qcow2'
    subprocess.run(['qemu-img', 'create', '-f', 'qcow2', str(source), '2M'], check=True, capture_output=True)
    subprocess.run(['qemu-img', 'convert', '-c', '-O', 'qcow2', str(source), str(target)], check=True)
    report = retained_report(source, target)
    report.update(source_sha256=sha256(source), compressed_sha256=sha256(target),
                  before={'identity': {str(source): tool.identity(source)}})
    (previous / 'result.json').write_text(json.dumps(report))
    monkeypatch.setattr(tool, 'alive', lambda _: None)
    # Only these disposable 2 MiB fixtures use a synthetic resource policy.
    monkeypatch.setattr(tool, 'config', lambda: {'builder': {'minimum_free_gib': 0}})
    return tool, tmp_path, run_id, source, target, report


def test_retained_copy_finalization_revalidates_and_keeps_old_report(tiny_retained_copy):
    import json
    from apexlib.common import sha256
    tool, root, run_id, source, target, old = tiny_retained_copy
    tool.resume_compaction(root, source, run_id)
    assert sha256(source) == old['compressed_sha256']
    assert not target.exists()
    assert json.loads((target.parent / 'result.json').read_text()) == old
    result = json.loads(next(target.parent.glob('finalize-*/result.json')).read_text())
    assert result['status'] == 'PASS' and result['replacement'] == 'COMPLETE'
    assert [c['argv'][1] for c in result['commands']] == ['info', 'info', 'check', 'check', 'compare']


@pytest.mark.parametrize('change', ['source-content', 'target-content', 'active-vm', 'low-space'])
def test_finalization_preserves_both_files_on_refusal(tiny_retained_copy, change, monkeypatch):
    from apexlib.common import sha256
    tool, root, run_id, source, target, old = tiny_retained_copy
    if change.endswith('content'):
        path = source if change == 'source-content' else target
        with path.open('ab') as stream:
            stream.write(b'changed')
    elif change == 'active-vm':
        monkeypatch.setattr(tool, 'alive', lambda _: {'pid': 1})
    else:
        monkeypatch.setattr(tool, 'config', lambda: {'builder': {'minimum_free_gib': 2**30}})
    before = {str(p): sha256(p) for p in (source, target)}
    with pytest.raises(Blocked):
        tool.resume_compaction(root, source, run_id)
    assert before == {str(p): sha256(p) for p in (source, target)}
