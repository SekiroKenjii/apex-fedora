"""A port that refuses every call.

It stands in for a real port during the phases where a stage may compute but never act:
discovery, preflight and planning. It is not written per port. Any method name a protocol
declares resolves to a function that raises, so a port that grows a method cannot leave a
gap in the double.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import NoReturn

from apex.kernel import claims, errors


class Refusing:
    environment = claims.EnvironmentKind.SIMULATED

    def __init__(self, port: str) -> None:
        self._port = port

    def __getattr__(self, name: str) -> Callable[..., NoReturn]:
        if name.startswith("_"):
            raise AttributeError(name)

        def refuse(*arguments: object, **keywords: object) -> NoReturn:
            raise errors.InternalDefect(
                f"{self._port}.{name} was called while only computing was permitted; "
                "a stage may act only in apply"
            )

        return refuse

    def __repr__(self) -> str:
        return f"<Refusing {self._port}>"
