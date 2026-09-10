"""Replace values that legitimately vary between runs with stable tokens.

A field not covered here must be stable. A field that appears or disappears is a
difference, and updating the baseline for one requires saying why.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[+-]\d{2}:\d{2}|Z)")
HEX32 = re.compile(r"\b[0-9a-f]{32}\b")
TEMPORARY_PATH = re.compile(r"/tmp/[^\s\"']+")
DURATION = re.compile(r"\b\d+\.\d{2,}s\b")
PYTHON_VERSION = re.compile(r"python3\.\d+")
TEMPORARY_NAME = re.compile(r"\btmp[a-z0-9_]{6,10}\b")
MEMORY_FIELD = re.compile(r'("(?:available_memory_mib|free_gib|required_free_gib)":\s*)\d+')


def _sequence_hex(text: str) -> str:
    seen: dict[str, str] = {}

    def replace(match: re.Match[str]) -> str:
        value = match.group(0)
        if value not in seen:
            seen[value] = f"<id-{len(seen)}>"
        return seen[value]

    return HEX32.sub(replace, text)


def normalise(text: str, *, root: str, repository: str) -> str:
    text = text.replace(root, "<root>").replace(repository, "<repo>")
    text = TIMESTAMP.sub("<ts>", text)
    text = TEMPORARY_PATH.sub("<tmp>", text)
    text = TEMPORARY_NAME.sub("<tmpname>", text)
    text = DURATION.sub("<elapsed>", text)
    text = PYTHON_VERSION.sub("python3.<minor>", text)
    text = MEMORY_FIELD.sub(r"\1<int>", text)
    return _sequence_hex(text)


def unstable_tokens() -> Iterator[str]:
    yield "<ts>"
    yield "<tmp>"
    yield "<tmpname>"
    yield "<elapsed>"
    yield "<root>"
    yield "<repo>"
