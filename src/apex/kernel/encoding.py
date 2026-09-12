"""One byte-stable rendering of a document.

A digest over a document only means something if every producer and every verifier render it
the same way. Keys are sorted, separators carry no padding, and non-ASCII is escaped, so the
bytes do not depend on the locale or on the order a mapping happened to be built in.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

type JsonValue = (
    str | int | float | bool | None | Sequence[JsonValue] | Mapping[str, JsonValue]
)
type Document = Mapping[str, JsonValue]


def parse_document(payload: bytes) -> JsonValue:
    """The value a JSON document holds, or `ValueError` when it is not one."""
    loaded: JsonValue = json.loads(payload)
    return loaded


def canonical(document: JsonValue) -> bytes:
    return json.dumps(
        document, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()
