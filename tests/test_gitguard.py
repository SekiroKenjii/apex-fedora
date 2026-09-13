import subprocess
from pathlib import Path
import pytest
from apexlib import gitguard
from apexlib.common import Blocked


@pytest.mark.parametrize("subject", ["feat(ui): add profile view", "fix(audio): initialize amplifier", "test: check recovery", "revert: feat(ui): add profile view"])
def test_subject_accepts_convention(subject):
    gitguard.validate_subject(subject + "\n")


@pytest.mark.parametrize("subject", ["update things", "feat: hi\n\n", "fix: hi\nCo-authored-by: person", "fix: " + "a" * 70, "fix: hi\rbye", "merge: update branch"])
def test_subject_rejects_bad_messages(subject):
    with pytest.raises(Blocked):
        gitguard.validate_subject(subject)


@pytest.mark.parametrize("path", ["AGENTS.md", ".claude/settings.json", "data/fingerprints/sample", "output/session.log", "cosign.key", "../outside", ".env.local", "tools/__pycache__/test.pyc", "device/sample.fpt"])
def test_private_paths(path):
    assert not gitguard.permitted(path)


@pytest.mark.parametrize("path", [
    "src/apex/agent/main.py", "src/apex/agent/units/x.py", "tests/unit/agent/test_main.py",
])
def test_the_agent_package_is_not_the_private_agent_directory(path):
    assert gitguard.permitted(path)


@pytest.mark.parametrize("path", [
    "agent/notes.md", "src/agent/main.py", "tests/agent/x.py", "docs/agent/x.md",
    "src/apex/Agent/x.py",
])
def test_every_other_agent_directory_stays_private(path):
    assert not gitguard.permitted(path)


def test_secret_detection():
    with pytest.raises(Blocked):
        gitguard.inspect_blob("config/test.txt", "100644", b"-----BEGIN " + b"OPENSSH PRIVATE KEY-----")


def test_local_marker_survives_document_rename():
    with pytest.raises(Blocked, match='Local-only'):
        gitguard.inspect_blob('docs/renamed.md', '100644', b'<!-- apex-' + b'local-only -->\nPrivate context')


@pytest.mark.parametrize('blob', [b'opaque\x00sensor\x01data', b'\xff\xfe\x80'])
def test_opaque_binary_cannot_pass_under_an_innocent_name(blob):
    with pytest.raises(Blocked, match='Binary source'):
        gitguard.inspect_blob('docs/example.txt', '100644', blob)


def test_utf8_product_documentation_is_allowed():
    gitguard.inspect_blob('docs/example.md', '100644', 'Kiểm thử máy ảo\n'.encode())


@pytest.fixture
def repo(tmp_path, monkeypatch):
    # Fixture commits must not inherit the contributor's signing or author settings.
    monkeypatch.setenv('GIT_CONFIG_GLOBAL', '/dev/null')
    monkeypatch.setenv('GIT_CONFIG_NOSYSTEM', '1')
    for name in ('GIT_INDEX_FILE', 'GIT_DIR', 'GIT_WORK_TREE', 'GIT_AUTHOR_NAME',
                 'GIT_AUTHOR_EMAIL', 'GIT_COMMITTER_NAME', 'GIT_COMMITTER_EMAIL'):
        monkeypatch.delenv(name, raising=False)
    subprocess.run(["git", "init", "-q", "-b", "main", str(tmp_path)], check=True)
    for key, value in (("user.name", "Fixture"), ("user.email", "fixture@example.invalid")):
        subprocess.run(["git", "-C", str(tmp_path), "config", key, value], check=True)
    return tmp_path


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


def test_index_checks_staged_content_not_worktree(repo):
    (repo / "settings.txt").write_text("-----BEGIN " + "RSA PRIVATE KEY-----")
    git(repo, "add", "settings.txt")
    (repo / "settings.txt").write_text("safe")
    with pytest.raises(Blocked):
        gitguard.inspect_tree(repo)


def test_push_checks_private_file_deleted_in_later_commit(repo):
    (repo / "AGENTS.md").write_text("private")
    git(repo, "add", "AGENTS.md")
    git(repo, "commit", "-qm", "docs: add notes")
    git(repo, "rm", "AGENTS.md")
    git(repo, "commit", "-qm", "docs: remove notes")
    sha = git(repo, "rev-parse", "HEAD")
    with pytest.raises(Blocked):
        gitguard.inspect_outgoing(repo, f"refs/heads/main {sha} refs/heads/main {'0'*40}\n")


def test_push_checks_commit_body(repo):
    (repo / 'code.txt').write_text('code')
    git(repo, 'add', 'code.txt')
    git(repo, 'commit', '-qm', 'feat: add code\n\nDetailed body')
    sha = git(repo, 'rev-parse', 'HEAD')
    with pytest.raises(Blocked):
        gitguard.inspect_outgoing(repo, f'refs/heads/main {sha} refs/heads/main {"0"*40}\n')


def test_push_skips_commits_a_remote_already_holds(repo):
    (repo / 'code.txt').write_text('code')
    git(repo, 'add', 'code.txt')
    git(repo, 'commit', '-qm', 'Merge pull request #2 from someone/branch')
    git(repo, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    (repo / 'more.txt').write_text('more')
    git(repo, 'add', 'more.txt')
    git(repo, 'commit', '-qm', 'feat: add more')
    sha = git(repo, 'rev-parse', 'HEAD')
    gitguard.inspect_outgoing(repo, f'refs/heads/topic {sha} refs/heads/topic {"0"*40}\n')


def test_push_still_checks_a_new_commit_after_one_a_remote_holds(repo):
    (repo / 'code.txt').write_text('code')
    git(repo, 'add', 'code.txt')
    git(repo, 'commit', '-qm', 'feat: add code')
    git(repo, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    (repo / 'more.txt').write_text('more')
    git(repo, 'add', 'more.txt')
    git(repo, 'commit', '-qm', 'feat: add more\n\nDetailed body')
    sha = git(repo, 'rev-parse', 'HEAD')
    with pytest.raises(Blocked):
        gitguard.inspect_outgoing(repo, f'refs/heads/topic {sha} refs/heads/topic {"0"*40}\n')


