"""What a rule is: a declaration, a subject it reads, and the findings it returns.

A rule returns findings rather than raising, so one pass reports everything wrong with a subject
instead of only the first thing found.

Rules are pure. They receive a value and return findings, and nothing in this module reads a
file, runs a program or holds state between calls.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence
from typing import Protocol

from apex.kernel import identifiers, quantities, refusals, treerows
from apex.workspace import ruleorigins


@dataclasses.dataclass(frozen=True, slots=True)
class EntrySubject:
    """One row of a tree or index: where it sits, what it is, and how big it claims to be."""

    path: treerows.RepoPath
    mode: treerows.EntryMode
    size: quantities.ByteCount | None


@dataclasses.dataclass(frozen=True, slots=True)
class ContentSubject:
    path: treerows.RepoPath
    payload: bytes


@dataclasses.dataclass(frozen=True, slots=True)
class MessageSubject:
    raw: str


@dataclasses.dataclass(frozen=True, slots=True)
class Finding:
    rule: identifiers.RuleId
    reason: refusals.RefusalReason
    subject: str
    remedy: str = ""


class InspectEntry(Protocol):
    def __call__(self, subject: EntrySubject) -> Sequence[Finding]: ...


class InspectContent(Protocol):
    def __call__(self, subject: ContentSubject) -> Sequence[Finding]: ...


class InspectMessage(Protocol):
    def __call__(self, subject: MessageSubject) -> Sequence[Finding]: ...


@dataclasses.dataclass(frozen=True, slots=True)
class EntryRule:
    id: identifiers.RuleId
    origin: ruleorigins.RuleOrigin
    inspect: InspectEntry


@dataclasses.dataclass(frozen=True, slots=True)
class ContentRule:
    id: identifiers.RuleId
    origin: ruleorigins.RuleOrigin
    inspect: InspectContent


@dataclasses.dataclass(frozen=True, slots=True)
class MessageRule:
    id: identifiers.RuleId
    origin: ruleorigins.RuleOrigin
    inspect: InspectMessage
