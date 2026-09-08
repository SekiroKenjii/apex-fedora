import subprocess
import shutil
from pathlib import Path
import pytest
from apexlib import gitguard
from apexlib.common import Blocked, ROOT


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


def test_hook_install_preserves_existing_hook(repo):
    path = repo / ".git/hooks/pre-commit"
    path.write_text("existing policy")
    with pytest.raises(Blocked):
        gitguard.install(repo)
    assert path.read_text() == "existing policy"


def test_push_checks_commit_body(repo):
    (repo / 'code.txt').write_text('code')
    git(repo, 'add', 'code.txt')
    git(repo, 'commit', '-qm', 'feat: add code\n\nDetailed body')
    sha = git(repo, 'rev-parse', 'HEAD')
    with pytest.raises(Blocked):
        gitguard.inspect_outgoing(repo, f'refs/heads/main {sha} refs/heads/main {"0"*40}\n')


def install_executable_hooks(repo):
    shutil.copytree(ROOT / 'tools', repo / 'tools', ignore=shutil.ignore_patterns('__pycache__'))
    gitguard.install(repo)


def attempt(repo, *args):
    return subprocess.run(['git', '-C', str(repo), *args], capture_output=True, text=True)


def test_real_pre_commit_blocks_local_file_and_allows_recovery(repo):
    install_executable_hooks(repo)
    (repo / 'AGENTS.md').write_text('local instructions')
    (repo / 'product.txt').write_text('product source')
    git(repo, 'add', 'AGENTS.md', 'product.txt')
    rejected = attempt(repo, 'commit', '-qm', 'build: add product')
    assert rejected.returncode != 0 and 'Private/local file' in rejected.stderr
    assert attempt(repo, 'rev-parse', '--verify', 'HEAD').returncode != 0
    git(repo, 'rm', '--cached', 'AGENTS.md')
    git(repo, 'commit', '-qm', 'build: add product')
    assert (repo / 'AGENTS.md').read_text() == 'local instructions'
    assert attempt(repo, 'check-ignore', 'AGENTS.md').returncode == 1
    assert git(repo, 'ls-tree', '--name-only', 'HEAD') == 'product.txt'


@pytest.mark.parametrize('message', [
    'update product', 'merge: update product', 'fix: ' + 'a' * 68,
    'fix: update product\n\nDetails',
    'fix: update product\n\nCo-authored-by: Fixture <fixture@example.invalid>',
])
def test_real_commit_msg_hook_rejects_invalid_commit(repo, message):
    install_executable_hooks(repo)
    (repo / 'product.txt').write_text('product source')
    git(repo, 'add', 'product.txt')
    rejected = attempt(repo, 'commit', '-qm', message)
    assert rejected.returncode != 0 and 'Conventional Commit' in rejected.stderr
    assert attempt(repo, 'rev-parse', '--verify', 'HEAD').returncode != 0


@pytest.mark.parametrize('bad_history', ['private-file', 'commit-body', None])
def test_real_pre_push_inspects_history_to_local_fixture_only(repo, bad_history):
    (repo / 'product.txt').write_text('product source')
    git(repo, 'add', 'product.txt')
    if bad_history == 'private-file':
        (repo / 'AGENTS.md').write_text('local instructions')
        git(repo, 'add', 'AGENTS.md')
    subject = 'build: add product' + ('\n\nDetails' if bad_history == 'commit-body' else '')
    # Create bad history before installing guards, then exercise the real push hook.
    git(repo, 'commit', '-qm', subject)
    if bad_history == 'private-file':
        git(repo, 'rm', 'AGENTS.md')
        git(repo, 'commit', '-qm', 'docs: remove local instructions')
    install_executable_hooks(repo)
    remote = repo / '.git/fixture-remote.git'
    git(repo, 'init', '--bare', '-q', str(remote))
    result = attempt(repo, 'push', str(remote), 'HEAD:refs/heads/main')
    assert (result.returncode == 0) == (bad_history is None)
    remote_head = attempt(remote, 'rev-parse', '--verify', 'refs/heads/main')
    if bad_history:
        assert 'BLOCKED:' in result.stderr
        assert remote_head.returncode != 0
    else:
        assert remote_head.stdout.strip() == git(repo, 'rev-parse', 'HEAD')
