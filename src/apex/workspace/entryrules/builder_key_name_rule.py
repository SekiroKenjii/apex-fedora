"""Private keys this project generates under names of its own."""

from __future__ import annotations

from collections.abc import Sequence

from apex.kernel import identifiers, refusals
from apex.workspace import entryrules, ruleorigins, rulespecs

RULE = identifiers.RuleId("repository.private-key-name")
NAMES = frozenset({"builder_ed25519", "deploy_key"})


def inspect(subject: rulespecs.EntrySubject) -> Sequence[rulespecs.Finding]:
    if subject.path.name_lowered not in NAMES:
        return ()
    return (
        rulespecs.Finding(
            rule=RULE,
            reason=refusals.RefusalReason.REPOSITORY_PRIVATE_KEY_NAME,
            subject=subject.path.value,
            remedy="keep the key on the machine that generated it",
        ),
    )



entryrules.declare(
    rulespecs.EntryRule(
        id=RULE,
        origin=ruleorigins.Introduced(
            phase="P12",
            why=(
                "the builder key exists in the real runtime root and the guard it replaces "
                "permits it by name; the two generic key names it does cover are handled by "
                "the private document rule"
            ),
        ),
        inspect=inspect,
    )
)
