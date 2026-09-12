"""A request names the protocol it speaks, and the agent refuses one it does not."""

from __future__ import annotations

import json

import pytest

from apex.agent import requests
from apex.kernel import errors, refusals

DIGEST = "a" * 64


def document(**overrides: object) -> bytes:
    body: dict[str, object] = {
        "protocol": requests.PROTOCOL_VERSION,
        "host_version": "0.2.0",
        "unit": "guest.state",
        "arguments": {},
        "agent_digest": DIGEST,
    }
    body.update(overrides)
    return json.dumps(body).encode()


def test_a_well_formed_request_parses() -> None:
    request = requests.AgentRequest.parse(document(arguments={"depth": 2}))

    assert str(request.unit) == "guest.state"
    assert request.arguments == {"depth": 2}
    assert request.agent_digest.hex == DIGEST
    assert request.host_version == "0.2.0"


def test_a_request_round_trips_through_its_document() -> None:
    request = requests.AgentRequest.parse(document())

    assert requests.AgentRequest.parse(json.dumps(request.document()).encode()) == request


@pytest.mark.parametrize("protocol", [0, 2, "1", None])
def test_another_protocol_is_refused(protocol: object) -> None:
    with pytest.raises(errors.Refusal) as raised:
        requests.AgentRequest.parse(document(protocol=protocol))

    assert raised.value.reason is refusals.RefusalReason.PROTOCOL_MISMATCH


@pytest.mark.parametrize(
    "payload",
    [
        b"nope",
        b"[]",
        document(unit="Not Dotted"),
        document(arguments=[]),
        document(agent_digest="short"),
        document(host_version=3),
    ],
)
def test_a_malformed_request_is_refused(payload: bytes) -> None:
    with pytest.raises(errors.Refusal) as raised:
        requests.AgentRequest.parse(payload)

    assert raised.value.reason is refusals.RefusalReason.REQUEST_MALFORMED


def test_a_reply_carries_the_protocol_and_the_unit() -> None:
    request = requests.AgentRequest.parse(document())

    reply = requests.AgentReply.answering(request, observations={"kernel": "7.0.0"})

    assert reply.document() == {
        "protocol": requests.PROTOCOL_VERSION,
        "unit": "guest.state",
        "observations": {"kernel": "7.0.0"},
    }


def test_the_handshake_names_the_protocol_and_the_agent_version() -> None:
    assert requests.handshake("0.2.0") == {
        "protocol": requests.PROTOCOL_VERSION,
        "agent_version": "0.2.0",
    }
