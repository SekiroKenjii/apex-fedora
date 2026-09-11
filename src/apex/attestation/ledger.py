"""An append-only chain of attestation entries.

Each link commits to the link before it and to the canonical rendering of its own entry, so
editing, removing or reordering an entry breaks the chain at a sequence the report can name.
A separate head record carries the latest sequence, because dropping entries off the end
leaves a shorter chain that is otherwise internally consistent.

Every line carries a message authentication code. The key lives beside the chain under the
same account, so this detects an edit made without the key and an accidental rewrite. It does
not withstand the operator of the machine, and no text in this project may claim it does.
"""

from __future__ import annotations

import dataclasses
import enum
import hashlib
import hmac
import json
from collections.abc import Sequence

from apex.attestation import proofs
from apex.kernel import (
    claims,
    encoding,
    errors,
    hashing,
    identifiers,
    quantities,
    refusals,
    secrets,
    verdicts,
)
from apex.ports import clock, files

GENESIS = identifiers.Digest("0" * 64)
BEFORE_FIRST = -1
CHAIN_NAME = "chain.jsonl"
HEAD_NAME = "head.json"
LEDGER_DIRECTORY = "ledger"
LINE_LIMIT = 1024 * 1024
CHAIN_LIMIT = 1024 * 1024 * 64
RECORD_MODE = quantities.FileMode(0o600)


class EntryKind(enum.StrEnum):
    """What an entry does to the record it names.

    A recorded result was produced by the ports that ran the check. An imported one was read
    out of the store the pre-restructure tools wrote, where no port witnessed anything, and it
    carries the permanent limits in `attesting.LEGACY_LIMITS` for as long as it exists.
    """

    RECORDED = "recorded"
    IMPORTED = "imported"


class Break(enum.StrEnum):
    MALFORMED_LINE = "malformed-line"
    SEQUENCE_OUT_OF_ORDER = "sequence-out-of-order"
    LINK_MISMATCH = "link-mismatch"
    MAC_MISMATCH = "mac-mismatch"
    HEAD_AHEAD_OF_CHAIN = "head-ahead-of-chain"


class _HmacSink:
    """The only route the key material takes, and it leaves as a tag rather than a value."""

    def __init__(self, payload: bytes) -> None:
        self._payload = payload
        self.tag = ""

    def accept(self, material: str) -> None:
        self.tag = hmac.new(material.encode(), self._payload, hashlib.sha256).hexdigest()


class ChainSigner:
    __slots__ = ("_key",)

    def __init__(self, key: secrets.Secret[str]) -> None:
        self._key = key

    def sign(self, link: identifiers.Digest) -> str:
        sink = _HmacSink(link.hex.encode())
        self._key.reveal_into(sink)
        return sink.tag

    def confirms(self, link: identifiers.Digest, tag: str) -> bool:
        return hmac.compare_digest(self.sign(link), tag)

    def __repr__(self) -> str:
        return "<ChainSigner>"


@dataclasses.dataclass(frozen=True, slots=True)
class Event:
    kind: EntryKind
    check: identifiers.CheckId
    verdict: verdicts.Verdict
    environment: claims.EnvironmentKind
    candidate: identifiers.Digest
    proofs: tuple[identifiers.Digest, ...]
    scope_limits: tuple[claims.ScopeLimit, ...]


@dataclasses.dataclass(frozen=True, slots=True)
class Entry:
    sequence: int
    stamp: str
    event: Event

    def document(self) -> encoding.Document:
        return {
            "sequence": self.sequence,
            "stamp": self.stamp,
            "kind": str(self.event.kind),
            "check": str(self.event.check),
            "verdict": self.event.verdict.stored_name,
            "environment": str(self.event.environment),
            "candidate": self.event.candidate.hex,
            "proofs": [item.hex for item in self.event.proofs],
            "scope_limits": [str(item) for item in self.event.scope_limits],
        }


@dataclasses.dataclass(frozen=True, slots=True)
class Sealed:
    entry: Entry
    link: identifiers.Digest
    tag: str

    def line(self) -> bytes:
        return encoding.canonical(
            {"entry": self.entry.document(), "link": self.link.hex, "mac": self.tag}
        )


@dataclasses.dataclass(frozen=True, slots=True)
class Head:
    sequence: int
    link: identifiers.Digest


@dataclasses.dataclass(frozen=True, slots=True)
class Breakage:
    sequence: int
    cause: Break


@dataclasses.dataclass(frozen=True, slots=True)
class Report:
    entries: int
    first_break: Breakage | None

    @property
    def intact(self) -> bool:
        return self.first_break is None


EMPTY = Head(sequence=BEFORE_FIRST, link=GENESIS)


def _stored_head(
    location: proofs.StoreLocation, filesystem: files.FileSystemPort
) -> Head | None:
    """Continue an existing chain rather than starting a second one over it."""
    path = location.head_path()
    if not filesystem.exists(path):
        return None
    try:
        document = json.loads(filesystem.read_bytes(path, limit=LINE_LIMIT))
        return Head(
            sequence=int(document["sequence"]),
            link=identifiers.Digest(str(document["link"])),
        )
    except (json.JSONDecodeError, KeyError, TypeError, ValueError, errors.Refusal) as error:
        raise errors.Refusal(
            refusals.RefusalReason.STALE_EVIDENCE,
            subject=str(path),
            remedy="the head record is unreadable, so the chain cannot be continued safely",
        ) from error


def read_chain(
    location: proofs.StoreLocation, filesystem: files.FileSystemPort, *, limit: int = CHAIN_LIMIT
) -> tuple[list[bytes], Head | None]:
    path = location.chain_path()
    body = filesystem.read_bytes(path, limit=limit) if filesystem.exists(path) else b""
    return [line for line in body.split(b"\n") if line], _stored_head(location, filesystem)


def link_after(previous: identifiers.Digest, entry: Entry) -> identifiers.Digest:
    return hashing.digest_bytes(
        previous.hex.encode() + encoding.canonical(entry.document())
    )


class Ledger:
    def __init__(
        self,
        *,
        location: proofs.StoreLocation,
        filesystem: files.FileSystemPort,
        signer: ChainSigner,
        clock: clock.ClockPort,
    ) -> None:
        self._location = location
        self._files = filesystem
        self._signer = signer
        self._clock = clock
        self._head = _stored_head(location, filesystem) or EMPTY

    def head(self) -> Head:
        return self._head

    def append(self, event: Event) -> Sealed:
        """Add one entry. There is no other way to change what the chain says."""
        claims.require_attestable(event.environment)
        entry = Entry(
            sequence=self._head.sequence + 1,
            stamp=self._clock.stamp().rendered,
            event=event,
        )
        link = link_after(self._head.link, entry)
        sealed = Sealed(entry=entry, link=link, tag=self._signer.sign(link))
        self._files.append_line(self._location.chain_path(), sealed.line(), mode=RECORD_MODE)
        self._head = Head(sequence=entry.sequence, link=link)
        self._files.write_atomic(
            self._location.head_path(),
            encoding.canonical({"sequence": self._head.sequence, "link": self._head.link.hex}),
            mode=RECORD_MODE,
        )
        return sealed


def _parse(line: bytes) -> Sealed | None:
    if len(line) > LINE_LIMIT:
        return None
    try:
        document = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(document, dict):
        return None
    try:
        body = document["entry"]
        event = Event(
            kind=EntryKind(body["kind"]),
            check=identifiers.CheckId(body["check"]),
            verdict=verdicts.parse(
                body["verdict"], reason=refusals.RefusalReason.NO_VERIFIED_RESULT
            ),
            environment=claims.EnvironmentKind(body["environment"]),
            candidate=identifiers.Digest(body["candidate"]),
            proofs=tuple(identifiers.Digest(item) for item in body["proofs"]),
            scope_limits=tuple(claims.ScopeLimit(item) for item in body["scope_limits"]),
        )
        entry = Entry(sequence=int(body["sequence"]), stamp=str(body["stamp"]), event=event)
        return Sealed(
            entry=entry,
            link=identifiers.Digest(document["link"]),
            tag=str(document["mac"]),
        )
    except (KeyError, TypeError, ValueError, errors.Refusal):
        return None


def replay(
    lines: Sequence[bytes], *, signer: ChainSigner, head: Head | None
) -> Report:
    """Decide over lines alone. Nothing here reads a file or trusts a stored digest."""
    previous = GENESIS
    expected = 0
    for position, line in enumerate(lines):
        sealed = _parse(line)
        if sealed is None:
            return Report(entries=position, first_break=Breakage(expected, Break.MALFORMED_LINE))
        if sealed.entry.sequence != expected:
            return Report(
                entries=position,
                first_break=Breakage(sealed.entry.sequence, Break.SEQUENCE_OUT_OF_ORDER),
            )
        if not signer.confirms(sealed.link, sealed.tag):
            return Report(
                entries=position, first_break=Breakage(expected, Break.MAC_MISMATCH)
            )
        if sealed.link != link_after(previous, sealed.entry):
            return Report(
                entries=position, first_break=Breakage(expected, Break.LINK_MISMATCH)
            )
        previous = sealed.link
        expected += 1
    if head is not None and (head.sequence != expected - 1 or head.link != previous):
        return Report(
            entries=len(lines), first_break=Breakage(head.sequence, Break.HEAD_AHEAD_OF_CHAIN)
        )
    return Report(entries=len(lines), first_break=None)
