"""The passphrase file the signing steps write next to a key."""

from __future__ import annotations

from collections.abc import Sequence

from apex.kernel import identifiers, refusals
from apex.workspace import entryrules, ruleorigins, rulespecs

RULE = identifiers.RuleId("repository.passphrase-file")
NAME = "passphrase"


def inspect(subject: rulespecs.EntrySubject) -> Sequence[rulespecs.Finding]:
    if subject.path.name_lowered != NAME:
        return ()
    return (
        rulespecs.Finding(
            rule=RULE,
            reason=refusals.RefusalReason.REPOSITORY_PASSPHRASE_FILE,
            subject=subject.path.value,
            remedy="a passphrase belongs with the key, outside the repository",
        ),
    )



entryrules.declare(
    rulespecs.EntryRule(
        id=RULE,
        origin=ruleorigins.Introduced(
            phase="P12",
            why=(
                "the signing and fixture steps write this exact name, and the guard it "
                "replaces permits it"
            ),
        ),
        inspect=inspect,
    )
)
