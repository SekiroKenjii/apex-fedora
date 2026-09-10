"""The boundaries of each path rule, stated one at a time.

The guard being replaced holds all of these in a single boolean expression, and no test
currently asserts that it PERMITS anything, so nothing constrains a decomposition that refuses
too much. Every case here names the rule it is about.
"""

from __future__ import annotations

import pytest

from apex.kernel import quantities, refusals, treerows
from apex.workspace import entryrules, gitguarding, rulespecs

RULES = None


def reasons(path: str, *, mode: treerows.EntryMode = treerows.EntryMode.REGULAR,
            size: int | None = None) -> set[refusals.RefusalReason]:
    subject = rulespecs.EntrySubject(
        path=treerows.RepoPath(path),
        mode=mode,
        size=None if size is None else quantities.ByteCount(size),
    )
    return {
        finding.reason
        for finding in gitguarding.judge_entry(subject, rules=entryrules.registered())
    }


@pytest.mark.parametrize(
    "name",
    ["agents.md", "claude.md", "handover.md", "memory.md", ".env", "cosign.key",
     "id_rsa", "id_ed25519"],
)
def test_all_eight_legacy_private_names_are_refused(name: str) -> None:
    """Including both key names, which must not move to a rule that refuses more.

    A rule that refuses more is excluded when the transcription is checked for fidelity, so
    moving them there would make them permitted in exactly the configuration meant to prove
    nothing was dropped.
    """
    assert reasons(f"docs/{name}")


def test_a_mixed_case_private_document_is_refused_and_a_source_file_is_not() -> None:
    assert refusals.RefusalReason.REPOSITORY_PRIVATE_DOCUMENT in reasons("docs/AGENTS.md")
    assert reasons("src/apex/kernel/errors.py") == set()


def test_the_environment_prefix_carries_its_dot() -> None:
    assert reasons(".envrc") == set()
    assert refusals.RefusalReason.REPOSITORY_ENVIRONMENT_FILE in reasons(".env.local")


def test_a_file_named_after_a_private_directory_is_permitted() -> None:
    """Only the components above the file are examined."""
    assert reasons("logs") == set()
    assert refusals.RefusalReason.REPOSITORY_PRIVATE_DIRECTORY in reasons("a/logs/b.txt")


def test_only_the_last_suffix_decides() -> None:
    assert reasons("x.tar.gz") == set()
    assert reasons("dir.log/f.txt") == set()
    assert refusals.RefusalReason.REPOSITORY_PRIVATE_ARTIFACT in reasons("x.txt.log")


def test_an_absolute_path_and_an_escaping_path_are_refused() -> None:
    assert refusals.RefusalReason.REPOSITORY_ABSOLUTE_PATH in reasons("/etc/passwd")
    assert refusals.RefusalReason.REPOSITORY_PATH_ESCAPES in reasons("a/../b.txt")


def test_a_gitlink_and_a_symlink_are_refused_by_different_rules() -> None:
    assert refusals.RefusalReason.PATH_IS_A_SYMLINK in reasons(
        "a.txt", mode=treerows.EntryMode.SYMLINK
    )
    assert refusals.RefusalReason.ARCHIVE_ENTRY_NOT_REGULAR in reasons(
        "a.txt", mode=treerows.EntryMode.GITLINK
    )


def test_an_oversize_blob_is_refused_from_its_declared_size() -> None:
    """Refused before its bytes are read, which is the point of deciding on the size."""
    assert reasons("a.txt", size=1024) == set()
    assert refusals.RefusalReason.REPOSITORY_BLOB_TOO_LARGE in reasons(
        "a.txt", size=20 * 1024 * 1024 + 1
    )


@pytest.mark.parametrize(
    ("path", "reason"),
    [
        ("config/credentials.json", refusals.RefusalReason.REPOSITORY_CREDENTIAL_DOCUMENT),
        ("build/passphrase", refusals.RefusalReason.REPOSITORY_PASSPHRASE_FILE),
        ("keys/builder_ed25519", refusals.RefusalReason.REPOSITORY_PRIVATE_KEY_NAME),
        ("secrets/token", refusals.RefusalReason.REPOSITORY_TOKEN_DOCUMENT),
        ("home/.netrc", refusals.RefusalReason.REPOSITORY_TOKEN_DOCUMENT),
    ],
)
def test_the_secrets_this_project_writes_are_refused(
    path: str, reason: refusals.RefusalReason
) -> None:
    """Each of these is permitted by the guard being replaced. Measured, not assumed."""
    assert reason in reasons(path)
