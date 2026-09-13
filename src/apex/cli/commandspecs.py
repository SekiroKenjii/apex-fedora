"""What a command is, separately from which ones exist.

A command receives its arguments and the context the composition root built, and returns a
reply: the one document standard output carries, or the text the operator asked for in its
place, the narrative for standard error, and the exit code. Nothing in a command prints, and
nothing in a command builds a port; both are the presentation layer's and the root's. A
command also says which justfile recipes invoke it, so the justfile is rendered from the
registry and a recipe can never name a command that does not exist.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Sequence
from typing import Protocol

from apex.kernel import encoding
from apex.wiring import contexts


def no_input() -> str:
    return ""


@dataclasses.dataclass(frozen=True, slots=True)
class Request:
    arguments: Sequence[str]
    context: contexts.Context
    read_input: Callable[[], str] = no_input


@dataclasses.dataclass(frozen=True, slots=True)
class Reply:
    document: encoding.JsonValue | None = None
    text: str | None = None
    narrative: str = ""
    exit_code: int = 0


class Run(Protocol):
    def __call__(self, request: Request) -> Reply: ...


@dataclasses.dataclass(frozen=True, slots=True)
class Recipe:
    """One justfile recipe: its name, its parameters as just spells them, and the command
    line it runs, where a parameter is written `{{name}}` and quoted by the renderer."""

    name: str
    parameters: tuple[str, ...]
    argv: tuple[str, ...]


@dataclasses.dataclass(frozen=True, slots=True)
class Command:
    name: str
    summary: str
    run: Run
    recipes: tuple[Recipe, ...] = ()
