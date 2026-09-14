"""Any environment file beyond the bare name, such as `.env.local`.

The prefix carries its trailing dot, so `.envrc` is an ordinary file and stays permitted.
"""

from __future__ import annotations

from collections.abc import Sequence

from apex.kernel import identifiers, refusals
from apex.workspace import entryrules, ruleorigins, rulespecs

RULE = identifiers.RuleId("repository.environment-file")
PREFIX = ".env."


def inspect(subject: rulespecs.EntrySubject) -> Sequence[rulespecs.Finding]:
    if not subject.path.name_lowered.startswith(PREFIX):
        return ()
    return (
        rulespecs.Finding(
            rule=RULE,
            reason=refusals.RefusalReason.REPOSITORY_ENVIRONMENT_FILE,
            subject=subject.path.value,
            remedy="environment files hold machine settings and stay out of the repository",
        ),
    )


entryrules.declare(
    rulespecs.EntryRule(
        id=RULE, origin=ruleorigins.Decomposed(ruleorigins.LegacySurface.PERMITTED), inspect=inspect
    )
)
