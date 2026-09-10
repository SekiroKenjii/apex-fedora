"""How a git row is read, before any rule looks at it.

Reading a row and judging it are separate. A path knows how to answer questions about itself, a
mode knows whether it carries a blob, and neither decides anything. Rules do that.

Parsing a mode is total: an unrecognised one is refused rather than returned, because a value a
rule has to guess about is a gap between rules.
"""

from __future__ import annotations

import dataclasses
import enum
import pathlib
from typing import Self

from apex.kernel import errors, refusals

UPWARD = ".."


class EntryMode(enum.StrEnum):
    REGULAR = "100644"
    EXECUTABLE = "100755"
    SYMLINK = "120000"
    GITLINK = "160000"

    @classmethod
    def parse(cls, raw: str) -> Self:
        try:
            return cls(raw)
        except ValueError as error:
            raise errors.Refusal(
                refusals.RefusalReason.MALFORMED_TREE_ROW,
                subject=raw,
                remedy="a tree row carries a file, an executable, a link or a submodule",
            ) from error

    @property
    def carries_blob(self) -> bool:
        return self in {EntryMode.REGULAR, EntryMode.EXECUTABLE}


@dataclasses.dataclass(frozen=True, slots=True)
class RepoPath:
    """A tracked path, answering the questions rules ask of one.

    It delegates to `PurePosixPath` rather than splitting the string itself. Reimplementing the
    parsing meant reimplementing its treatment of `.`, of a trailing `..` and of the leading
    separator, and a differential run found seven paths where the two disagreed. None of them
    changed a verdict, but only because the differing component happened not to be in any rule's
    set, and a rule set is the thing most likely to grow.
    """

    value: str

    @property
    def _parsed(self) -> pathlib.PurePosixPath:
        return pathlib.PurePosixPath(self.value)

    @property
    def components(self) -> tuple[str, ...]:
        return self._parsed.parts

    @property
    def directory_components(self) -> tuple[str, ...]:
        return self._parsed.parts[:-1]

    @property
    def name_lowered(self) -> str:
        """Lowered, never case folded.

        Folding maps ten characters into ASCII that lowering does not, so it would refuse paths
        the guard being replaced permits. A wider rule is still a different rule.
        """
        return self._parsed.name.lower()

    @property
    def suffix_lowered(self) -> str:
        return self._parsed.suffix.lower()

    @property
    def is_absolute(self) -> bool:
        return self._parsed.is_absolute()

    @property
    def traverses_upward(self) -> bool:
        return UPWARD in self._parsed.parts
