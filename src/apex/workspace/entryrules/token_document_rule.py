"""Files whose whole purpose is to carry a credential for something else."""

from __future__ import annotations

from collections.abc import Sequence

from apex.kernel import identifiers, refusals
from apex.workspace import entryrules, ruleorigins, rulespecs

RULE = identifiers.RuleId("repository.token-document")
NAMES = frozenset({"token", ".netrc", ".git-credentials"})
SUFFIX = ".token"


def inspect(subject: rulespecs.EntrySubject) -> Sequence[rulespecs.Finding]:
    if subject.path.name_lowered not in NAMES and subject.path.suffix_lowered != SUFFIX:
        return ()
    return (
        rulespecs.Finding(
            rule=RULE,
            reason=refusals.RefusalReason.REPOSITORY_TOKEN_DOCUMENT,
            subject=subject.path.value,
            remedy="a stored credential belongs outside the repository",
        ),
    )


entryrules.declare(
    rulespecs.EntryRule(
        id=RULE,
        origin=ruleorigins.Introduced(
            phase="P12",
            why=(
                "the guard it replaces matches two forge token shapes inside a file's "
                "contents and no file whose name says it holds one"
            ),
        ),
        inspect=inspect,
    )
)
