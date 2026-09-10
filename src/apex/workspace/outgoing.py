"""Which commits a push would add, read off the lines Git supplies on standard input.

A branch being deleted has nothing to inspect. A remote whose history is not present locally
cannot be subtracted, so it is refused rather than silently treated as an empty remote, which
would offer every commit in the branch for inspection and take far longer than the operator
expects.

Nothing here runs a program. It turns update lines into a selection, and the caller resolves it.
"""

from __future__ import annotations

import dataclasses

from apex.kernel import errors, refusals

FIELDS = 4
ABSENT = "0"


@dataclasses.dataclass(frozen=True, slots=True)
class Update:
    local_reference: str
    local_commit: str
    remote_reference: str
    remote_commit: str

    @property
    def deletes_the_branch(self) -> bool:
        return set(self.local_commit) == {ABSENT}

    @property
    def creates_the_branch(self) -> bool:
        return set(self.remote_commit) == {ABSENT}


def parse_update(line: str) -> Update:
    fields = line.split()
    if len(fields) != FIELDS:
        raise errors.Refusal(
            refusals.RefusalReason.REPOSITORY_UPDATE_LINE_MALFORMED,
            subject=line,
            remedy="each update line names a local reference, its commit, and the remote pair",
        )
    return Update(*fields)


def updates(raw: str) -> tuple[Update, ...]:
    return tuple(parse_update(line) for line in raw.splitlines() if line.strip())


def revision_arguments(update: Update, *, remote_is_known: bool) -> tuple[str, ...]:
    """The revision range whose commits this push would add.

    Refusing an unknown remote is the point: subtracting nothing offers the whole branch, and a
    push that inspects thousands of commits looks like a hang rather than a check.
    """
    if update.deletes_the_branch:
        return ()
    if update.creates_the_branch:
        return (update.local_commit,)
    if not remote_is_known:
        raise errors.Refusal(
            refusals.RefusalReason.REPOSITORY_HISTORY_NOT_FETCHED,
            subject=update.remote_commit,
            remedy="fetch the remote history before checking this push",
        )
    return (update.local_commit, f"^{update.remote_commit}")
