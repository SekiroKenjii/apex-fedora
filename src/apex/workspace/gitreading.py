"""Reading what Git holds, through the process port, without deciding anything about it.

Every question a hook asks Git is here: the index rows, a commit's tree rows, the sizes of
objects and their bytes in one batch each, a commit's message, and the commits a push would
add. A failed git command is a refusal with git's own words, and a batch the port had to cut
short is refused rather than judged in part, because a guard that saw half the content and
permitted the rest would look exactly like one that was working.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from apex.config import defaults
from apex.kernel import commands, errors, quantities, refusals, safepaths
from apex.ports import process
from apex.workspace import outgoing, staging

BLANK_LINE = b"\n\n"
MISSING = "missing"


def _git(
    processes: process.ProcessPort,
    repository: Path,
    *arguments: str,
    stdin: bytes | None = None,
    limit: commands.OutputLimit | None = None,
) -> bytes:
    argv = commands.Argv.of("git", "-C", str(repository), *arguments)
    try:
        completed = processes.run(
            argv,
            deadline=defaults.HOOK_GIT_DEADLINE,
            limit=commands.OutputLimit.default() if limit is None else limit,
            stdin=stdin,
        )
    except errors.PortFailure as failure:
        raise errors.Refusal(
            refusals.RefusalReason.HOOK_GIT_FAILED, subject=f"git {arguments[0]}: {failure.cause}"
        ) from failure
    if not completed.succeeded:
        raise errors.Refusal(
            refusals.RefusalReason.HOOK_GIT_FAILED,
            subject=f"git {arguments[0]} exited {completed.exit_code}: "
            f"{completed.stderr.decode(errors='replace').strip()}",
        )
    if completed.truncated:
        raise errors.Refusal(
            refusals.RefusalReason.HOOK_CONTENT_UNREAD,
            subject=f"git {arguments[0]}: the answer did not fit in the port's limit",
            remedy="commit fewer or smaller files at once",
        )
    return completed.stdout


def staged_rows(processes: process.ProcessPort, repository: Path) -> tuple[staging.Row, ...]:
    return staging.index_rows(_git(processes, repository, "ls-files", "--stage", "-z"))


def tree_rows(
    processes: process.ProcessPort, repository: Path, commit: str
) -> tuple[staging.Row, ...]:
    return staging.tree_rows(_git(processes, repository, "ls-tree", "-rz", commit))


def sizes(
    processes: process.ProcessPort, repository: Path, names: Sequence[str]
) -> dict[str, quantities.ByteCount]:
    """Each object's size as the object database reports it, without reading its bytes."""
    if not names:
        return {}
    answer = _git(
        processes, repository, "cat-file", "--batch-check",
        stdin="".join(f"{name}\n" for name in names).encode(),
    )
    found: dict[str, quantities.ByteCount] = {}
    for line in answer.decode(errors="replace").splitlines():
        fields = line.split()
        if len(fields) == 3 and fields[1] != MISSING:
            found[fields[0]] = quantities.ByteCount(int(fields[2]))
    absent = [name for name in names if name not in found]
    if absent:
        raise errors.Refusal(
            refusals.RefusalReason.HOOK_GIT_FAILED,
            subject=f"objects not in the database: {', '.join(absent[:3])}",
        )
    return found


def contents(
    processes: process.ProcessPort, repository: Path, names: Sequence[str]
) -> dict[str, bytes]:
    """Each object's bytes, in one batch, refused whole when the batch could not come whole."""
    if not names:
        return {}
    answer = _git(
        processes, repository, "cat-file", "--batch",
        stdin="".join(f"{name}\n" for name in names).encode(),
        limit=commands.OutputLimit(defaults.HOOK_CONTENT_LIMIT.value),
    )
    found: dict[str, bytes] = {}
    at = 0
    while at < len(answer):
        end = answer.index(b"\n", at)
        fields = answer[at:end].decode(errors="replace").split()
        at = end + 1
        if len(fields) != 3:
            continue
        size = int(fields[2])
        found[fields[0]] = answer[at:at + size]
        at += size + 1
    absent = [name for name in names if name not in found]
    if absent:
        raise errors.Refusal(
            refusals.RefusalReason.HOOK_CONTENT_UNREAD,
            subject=f"objects not read: {', '.join(absent[:3])}",
        )
    return found


def commit_message(processes: process.ProcessPort, repository: Path, commit: str) -> str:
    """The message as the commit object carries it, after its header."""
    raw = _git(processes, repository, "cat-file", "commit", commit)
    _, separator, message = raw.partition(BLANK_LINE)
    if not separator:
        raise errors.Refusal(
            refusals.RefusalReason.HOOK_GIT_FAILED, subject=f"{commit}: no message in the commit"
        )
    return message.decode(errors="replace")


def remote_is_known(processes: process.ProcessPort, repository: Path, commit: str) -> bool:
    try:
        _git(processes, repository, "cat-file", "-e", commit)
    except errors.Refusal as refusal:
        if refusal.reason is refusals.RefusalReason.HOOK_GIT_FAILED:
            return False
        raise
    return True


def outgoing_commits(
    processes: process.ProcessPort, repository: Path, update: outgoing.Update
) -> tuple[str, ...]:
    """The commits this update would add, oldest first, that no remote already holds."""
    if update.deletes_the_branch:
        return ()
    known = update.creates_the_branch or remote_is_known(
        processes, repository, update.remote_commit
    )
    selection = outgoing.revision_arguments(update, remote_is_known=known)
    answer = _git(
        processes, repository, "rev-list", "--reverse", *selection, "--not", "--remotes"
    )
    return tuple(answer.decode(errors="replace").split())


def hooks_directory(processes: process.ProcessPort, repository: Path) -> safepaths.SafePath:
    """Where this checkout's hooks live: the common directory's for a worktree, and
    `core.hooksPath` when the operator set one, since Git resolves both."""
    answer = _git(processes, repository, "rev-parse", "--git-path", "hooks")
    return safepaths.SafePath((repository / answer.decode(errors="replace").strip()).resolve())
