"""The pre-push hook: every commit a push would add, its message and its whole tree.

Git names the updates on standard input. A branch being deleted adds nothing; a remote whose
history is not fetched is refused rather than treated as empty; every other update yields
the commits no remote already holds, and each is judged as the commit message hook and the
pre-commit hook would have judged it, with the commit named on every finding.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence

from apex.cli import hookkinds, hookspecs
from apex.workspace import gitguarding, gitreading, outgoing, rulespecs, treejudging

NAME = "pre-push"
SUBJECT = "the outgoing commits"
SHORT = 12


def _commit(request: hookspecs.HookRequest, commit: str) -> tuple[rulespecs.Finding, ...]:
    message = gitreading.commit_message(request.processes, request.repository, commit)
    findings = list(
        gitguarding.judge_message(
            rulespecs.MessageSubject(raw=message), rules=gitguarding.registered_message_rules()
        )
    )
    rows = gitreading.tree_rows(request.processes, request.repository, commit)
    sizes = gitreading.sizes(
        request.processes,
        request.repository,
        tuple({row.object_name: None for row in rows if row.mode.carries_blob}),
    )
    contents = gitreading.contents(
        request.processes, request.repository, treejudging.readable(rows, sizes)
    )
    findings.extend(
        treejudging.judge_rows(
            rows,
            sizes=sizes,
            contents=contents,
            entry_rules=gitguarding.registered_entry_rules(),
            content_rules=gitguarding.registered_content_rules(),
        )
    )
    return tuple(
        dataclasses.replace(item, subject=f"{commit[:SHORT]}: {item.subject}") for item in findings
    )


def inspect(request: hookspecs.HookRequest) -> Sequence[rulespecs.Finding]:
    findings: list[rulespecs.Finding] = []
    for update in outgoing.updates(request.standard_input):
        for commit in gitreading.outgoing_commits(request.processes, request.repository, update):
            findings.extend(_commit(request, commit))
    return tuple(findings)


hookkinds.declare(
    hookspecs.HookKind(
        name=NAME, subject=SUBJECT, remedy="rewrite the outgoing commits", inspect=inspect
    )
)
