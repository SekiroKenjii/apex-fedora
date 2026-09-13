"""Running the rules over a subject and collecting everything they find.

Every rule sees every subject it applies to, so one pass reports all of it: a message carrying
both a body and a co-author trailer is reported as both, not as the first one found.

The rule set is a parameter rather than a lookup, so a caller can run the transcribed rules
alone and compare that against the guard they transcribe. Nothing here caches: a verdict
belongs to a row, and two rows sharing one object still differ by the path they sit at.
"""

from __future__ import annotations

from collections.abc import Sequence

from apex.workspace import contentrules, entryrules, messagerules, ruleorigins, rulespecs


def judge_entry(
    subject: rulespecs.EntrySubject, *, rules: Sequence[rulespecs.EntryRule]
) -> tuple[rulespecs.Finding, ...]:
    return tuple(finding for rule in rules for finding in rule.inspect(subject))


def judge_content(
    subject: rulespecs.ContentSubject, *, rules: Sequence[rulespecs.ContentRule]
) -> tuple[rulespecs.Finding, ...]:
    return tuple(finding for rule in rules for finding in rule.inspect(subject))


def judge_message(
    subject: rulespecs.MessageSubject, *, rules: Sequence[rulespecs.MessageRule]
) -> tuple[rulespecs.Finding, ...]:
    return tuple(finding for rule in rules for finding in rule.inspect(subject))


def registered_entry_rules() -> tuple[rulespecs.EntryRule, ...]:
    return entryrules.registered()


def registered_content_rules() -> tuple[rulespecs.ContentRule, ...]:
    return contentrules.registered()


def registered_message_rules() -> tuple[rulespecs.MessageRule, ...]:
    return messagerules.registered()


def transcribed[RuleT: rulespecs.EntryRule | rulespecs.ContentRule | rulespecs.MessageRule](
    rules: Sequence[RuleT],
) -> tuple[RuleT, ...]:
    """Only the rules that transcribe an existing refusal.

    Comparing this set against the guard being replaced asks for agreement in both directions,
    which is a stronger claim than the full set can make and the one that says the transcription
    was faithful.
    """
    return tuple(rule for rule in rules if isinstance(rule.origin, ruleorigins.Decomposed))
