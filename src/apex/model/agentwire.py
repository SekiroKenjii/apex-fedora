"""What the host asks a guest to do, and what the guest answers.

A request names the protocol it speaks and the digest of the guest program the host shipped,
so a guest running another protocol or another build refuses before it runs anything. A
reply names the unit it answers for, so the host cannot file it under a different check.
"""

from __future__ import annotations

import dataclasses
import json
import re
from collections.abc import Mapping
from typing import Self

from apex.kernel import encoding, errors, identifiers, refusals

PROTOCOL_VERSION = 1
HEX_DIGEST = re.compile(r"[0-9a-f]{64}")


def _refuse(detail: str) -> errors.Refusal:
    return errors.Refusal(refusals.RefusalReason.REQUEST_MALFORMED, subject=detail)


def _document(payload: bytes) -> dict[str, object]:
    try:
        document = json.loads(payload)
    except (json.JSONDecodeError, UnicodeDecodeError) as fault:
        raise _refuse("not a JSON document") from fault
    if not isinstance(document, dict):
        raise _refuse("not an object")
    return document


def _protocol(document: Mapping[str, object]) -> None:
    protocol = document.get("protocol")
    if isinstance(protocol, bool) or protocol != PROTOCOL_VERSION:
        raise errors.Refusal(
            refusals.RefusalReason.PROTOCOL_MISMATCH,
            subject=f"request speaks protocol {protocol!r}",
            remedy=f"this guest speaks protocol {PROTOCOL_VERSION}",
        )


@dataclasses.dataclass(frozen=True, slots=True)
class AgentRequest:
    host_version: str
    unit: identifiers.ProbeId
    arguments: Mapping[str, encoding.JsonValue]
    agent_digest: identifiers.Digest

    @classmethod
    def parse(cls, payload: bytes) -> Self:
        document = _document(payload)
        _protocol(document)
        host_version = document.get("host_version")
        if not isinstance(host_version, str):
            raise _refuse(f"host_version {host_version!r}")
        unit = document.get("unit")
        if not isinstance(unit, str):
            raise _refuse(f"unit {unit!r}")
        arguments = document.get("arguments", {})
        if not isinstance(arguments, dict):
            raise _refuse("arguments must be an object")
        digest = document.get("agent_digest")
        if not isinstance(digest, str) or not HEX_DIGEST.fullmatch(digest):
            raise _refuse(f"agent_digest {digest!r}")
        try:
            named = identifiers.ProbeId(unit)
        except errors.Refusal as fault:
            raise _refuse(f"unit {unit!r}") from fault
        return cls(
            host_version=host_version,
            unit=named,
            arguments=arguments,
            agent_digest=identifiers.Digest(digest),
        )

    def document(self) -> encoding.Document:
        return {
            "protocol": PROTOCOL_VERSION,
            "host_version": self.host_version,
            "unit": str(self.unit),
            "arguments": dict(self.arguments),
            "agent_digest": self.agent_digest.hex,
        }


@dataclasses.dataclass(frozen=True, slots=True)
class AgentReply:
    unit: identifiers.ProbeId
    observations: encoding.Document

    @classmethod
    def answering(cls, request: AgentRequest, *, observations: encoding.Document) -> Self:
        return cls(unit=request.unit, observations=observations)

    def document(self) -> encoding.Document:
        return {
            "protocol": PROTOCOL_VERSION,
            "unit": str(self.unit),
            "observations": dict(self.observations),
        }

    @classmethod
    def parse(cls, payload: bytes) -> Self:
        document = _document(payload)
        _protocol(document)
        unit = document.get("unit")
        observations = document.get("observations")
        if not isinstance(unit, str):
            raise _refuse(f"unit {unit!r}")
        if not isinstance(observations, dict):
            raise _refuse("observations must be an object")
        try:
            named = identifiers.ProbeId(unit)
        except errors.Refusal as fault:
            raise _refuse(f"unit {unit!r}") from fault
        return cls(unit=named, observations=observations)


def handshake(agent_version: str) -> encoding.Document:
    return {"protocol": PROTOCOL_VERSION, "agent_version": agent_version}
