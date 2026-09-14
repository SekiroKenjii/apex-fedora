"""The commit message hook.

It reads a file and runs five pure rules. Nothing here executes a program or needs a repository,
which is exactly why this is the hook the rules take over first. The file is read as bytes,
because a text read folds a carriage return into a newline before the rule that refuses it
could see it.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from apex.cli import hookkinds, hookspecs
from apex.kernel import errors, refusals
from apex.workspace import gitguarding, rulespecs

NAME = "commit-msg"
SUBJECT = "this commit message"
ENCODING = "utf-8"


def inspect(request: hookspecs.HookRequest) -> Sequence[rulespecs.Finding]:
    if not request.arguments:
        raise errors.Refusal(
            refusals.RefusalReason.HOOK_ARGUMENT_MISSING,
            subject=NAME,
            remedy="Git passes the message file; this hook was called without it",
        )
    raw = Path(request.arguments[0]).read_bytes().decode(ENCODING)
    subject = rulespecs.MessageSubject(raw=raw)
    return gitguarding.judge_message(subject, rules=gitguarding.registered_message_rules())


hookkinds.declare(
    hookspecs.HookKind(name=NAME, subject=SUBJECT, remedy="change the message", inspect=inspect)
)
