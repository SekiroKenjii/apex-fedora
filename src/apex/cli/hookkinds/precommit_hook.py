"""The pre-commit hook: every staged row judged by its path, mode, size and bytes.

The rows come from the index, the sizes from the object database in one batch, and the
bytes of every blob the size rule would not refuse in a second batch, so a large file is
refused without being read and a small one is read exactly once.
"""

from __future__ import annotations

from collections.abc import Sequence

from apex.cli import hookkinds, hookspecs
from apex.workspace import gitguarding, gitreading, rulespecs, treejudging

NAME = "pre-commit"
SUBJECT = "what is staged"


def inspect(request: hookspecs.HookRequest) -> Sequence[rulespecs.Finding]:
    rows = gitreading.staged_rows(request.processes, request.repository)
    sizes = gitreading.sizes(
        request.processes, request.repository,
        tuple({row.object_name: None for row in rows if row.mode.carries_blob}),
    )
    contents = gitreading.contents(
        request.processes, request.repository, treejudging.readable(rows, sizes)
    )
    return treejudging.judge_rows(
        rows,
        sizes=sizes,
        contents=contents,
        entry_rules=gitguarding.registered_entry_rules(),
        content_rules=gitguarding.registered_content_rules(),
    )


hookkinds.declare(
    hookspecs.HookKind(
        name=NAME, subject=SUBJECT, remedy="change what is staged", inspect=inspect
    )
)
