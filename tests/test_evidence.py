import json
import pytest
from apexlib.evidence import evaluate, select
from apexlib.common import Blocked, sha256

DIGEST = "sha256:" + "a" * 64


def test_empty_evidence_never_ready(tmp_path):
    result = evaluate(tmp_path, None)
    assert not result["ready_to_install"]
    assert result["checks"]["hardware"]["audio.speakers"]["status"] == "NOT TESTED"


def put(tmp_path, record):
    record.setdefault('environment', {'kind': 'build', 'description': 'Unit test fixture'})
    directory = tmp_path / "evidence"
    directory.mkdir(exist_ok=True)
    (directory / "record.json").write_text(json.dumps(record))


def test_stale_digest_rejected(tmp_path):
    put(tmp_path, {"check": "image.lint", "digest": "sha256:" + "b" * 64, "status": "PASS"})
    assert evaluate(tmp_path, DIGEST)["errors"]


def test_vm_cannot_attest_hardware(tmp_path):
    put(tmp_path, {'check': 'audio.speakers', 'digest': DIGEST, 'status': 'BLOCKED', 'environment': {'kind': 'vm', 'description': 'QEMU'}})
    assert evaluate(tmp_path, DIGEST)['errors']


def test_pass_requires_proof(tmp_path):
    put(tmp_path, {"check": "image.lint", "digest": DIGEST, "status": "PASS"})
    assert evaluate(tmp_path, DIGEST)["errors"]


def test_proof_modified_after_capture(tmp_path):
    folder = tmp_path / "evidence"
    folder.mkdir()
    artifact = folder / "lint.txt"
    artifact.write_text("pass")
    put(tmp_path, {"check": "image.lint", "digest": DIGEST, "status": "PASS", "proof": [{"path": "lint.txt", "sha256": sha256(artifact)}]})
    assert not evaluate(tmp_path, DIGEST)["errors"]
    artifact.write_text("changed")
    assert evaluate(tmp_path, DIGEST)["errors"]


def test_hardware_is_not_satisfied_by_image_lint(tmp_path):
    put(tmp_path, {"check": "image.lint", "digest": DIGEST, "status": "BLOCKED"})
    assert not evaluate(tmp_path, DIGEST)["ready_to_install"]


def test_path_escape_rejected(tmp_path):
    path = tmp_path / "external.txt"
    path.write_text("pass")
    put(tmp_path, {"check": "image.lint", "digest": DIGEST, "status": "PASS", "proof": [{"path": "../external.txt", "sha256": sha256(path)}]})
    assert evaluate(tmp_path, DIGEST)["errors"]


def test_new_digest_archives_old_candidate_and_proof(tmp_path):
    select(tmp_path, {'digest': DIGEST})
    put(tmp_path, {'check': 'image.lint', 'digest': DIGEST, 'status': 'BLOCKED'})
    new_digest = 'sha256:' + 'b' * 64
    result = select(tmp_path, {'digest': new_digest})
    assert result['digest'] == new_digest
    assert result['checks']['build']['image.lint']['status'] == 'NOT TESTED'
    assert not result['ready_to_install']
    archive, = (tmp_path / 'candidate-history').iterdir()
    assert json.loads((archive / 'candidate.json').read_text())['digest'] == DIGEST
    assert not evaluate(archive, DIGEST)['errors']
    assert (archive / 'evidence/record.json').is_file()


def test_reselect_same_digest_retains_current_evidence(tmp_path):
    select(tmp_path, {'digest': DIGEST})
    put(tmp_path, {'check': 'image.lint', 'digest': DIGEST, 'status': 'BLOCKED'})
    select(tmp_path, {'digest': DIGEST})
    assert (tmp_path / 'evidence/record.json').exists()
    assert not (tmp_path / 'candidate-history').exists()


def test_orphan_evidence_cannot_be_assigned_to_new_candidate(tmp_path):
    put(tmp_path, {'check': 'image.lint', 'digest': DIGEST, 'status': 'BLOCKED'})
    with pytest.raises(Blocked, match='no candidate'):
        select(tmp_path, {'digest': DIGEST})


def test_candidate_selection_rejects_symlink_history(tmp_path):
    select(tmp_path, {'digest': DIGEST})
    (tmp_path / 'external').mkdir()
    (tmp_path / 'candidate-history').symlink_to(tmp_path / 'external', target_is_directory=True)
    with pytest.raises(Blocked, match='symlink'):
        select(tmp_path, {'digest': 'sha256:' + 'b' * 64})
    assert json.loads((tmp_path / 'candidate.json').read_text())['digest'] == DIGEST
