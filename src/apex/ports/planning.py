"""A port that refuses every call.

It stands in for a real port during the phases where a stage may compute but never act:
discovery, preflight and planning. It is not written per port. Any method name a protocol
declares resolves to a function that raises, so a port that grows a method cannot leave a
gap in the double.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, NoReturn

from apex.kernel import claims, errors


class Refusing:
    environment = claims.EnvironmentKind.SIMULATED

    def __init__(self, port: str) -> None:
        self._port = port

    def __getattr__(self, name: str) -> Callable[..., NoReturn]:
        if name.startswith("_"):
            raise AttributeError(name)

        def refuse(*_arguments: object, **_keywords: object) -> NoReturn:
            raise errors.InternalDefect(
                f"{self._port}.{name} was called while only computing was permitted; "
                "a stage may act only in apply"
            )

        return refuse

    def __repr__(self) -> str:
        return f"<Refusing {self._port}>"


def refusing(name: str) -> Any:
    """The refusing double, handed to a slot typed as the port it stands in for.

    The double answers every method name by refusing, so it satisfies any port at runtime.
    `Any` is the one place that fact is stated for the checker, instead of a cast per slot.
    """
    return Refusing(name)
