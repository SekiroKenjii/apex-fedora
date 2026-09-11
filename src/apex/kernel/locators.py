"""Where a thing is fetched from and what it is called, checked at construction.

A download port that only accepts an `HttpsUrl` cannot be handed a plain-text address, and a
cache that only accepts a `Basename` cannot be steered outside its directory.
"""

from __future__ import annotations

import dataclasses
import re

from apex.kernel import errors, refusals

HTTPS_SCHEME = "https://"
_PLAIN_NAME = re.compile(r"[A-Za-z0-9_.-]+")
_RELATIVE_SELF = frozenset({".", ".."})


@dataclasses.dataclass(frozen=True, slots=True)
class HttpsUrl:
    value: str

    def __post_init__(self) -> None:
        if not self.value.startswith(HTTPS_SCHEME) or len(self.value) == len(HTTPS_SCHEME):
            raise errors.Refusal(
                refusals.RefusalReason.URL_NOT_HTTPS,
                subject=self.value or "(empty)",
                remedy="downloads use https and nothing else",
            )

    def __str__(self) -> str:
        return self.value


@dataclasses.dataclass(frozen=True, slots=True)
class Basename:
    value: str

    def __post_init__(self) -> None:
        if not _PLAIN_NAME.fullmatch(self.value) or self.value in _RELATIVE_SELF:
            raise errors.Refusal(
                refusals.RefusalReason.FILENAME_NOT_PLAIN,
                subject=self.value or "(empty)",
                remedy=(
                    "a filename is one path component of letters, digits, dot, dash and "
                    "underscore"
                ),
            )

    def __str__(self) -> str:
        return self.value
