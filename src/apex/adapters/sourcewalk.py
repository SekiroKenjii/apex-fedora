"""Choosing which files a source set contains.

Both bundlers walk the same real tree and differ only in what they write, so the walk lives
here once. It was duplicated, and so was the defect: a directory test that follows links
discarded a symlinked subtree before anything examined the link, and a symlinked source root
was followed rather than refused.

A symlink is returned rather than filtered, so the caller refuses it by the rule it already
has. Deciding what to look at and deciding what is allowed stay separate.
"""

from __future__ import annotations

import dataclasses
import pathlib
from collections.abc import Iterator

from apex.kernel import errors, hashing, quantities, refusals
from apex.ports import archives

EXECUTABLE_SUFFIXES = frozenset({".sh"})
EXECUTABLE_MODE = quantities.FileMode(0o755)
ORDINARY_MODE = quantities.FileMode(0o644)
IGNORED_DIRECTORY = "__pycache__"


def mode_for(candidate: pathlib.Path) -> quantities.FileMode:
    return EXECUTABLE_MODE if candidate.suffix in EXECUTABLE_SUFFIXES else ORDINARY_MODE


def candidates(sources: archives.SourceSet) -> list[pathlib.Path]:
    """Every file a bundle would contain, each exactly once, symlinks included.

    Overlapping declared roots would otherwise present a file twice, and a file hashed twice
    is a root that no longer describes a set of files.
    """
    found: set[pathlib.Path] = set()
    for relative in sources.relative_paths:
        base = sources.root.path / relative
        if base.is_symlink():
            raise errors.Refusal(
                refusals.RefusalReason.PATH_IS_A_SYMLINK,
                subject=relative,
                remedy="declare the directory a source root, not a link to it",
            )
        if not base.exists():
            continue
        walked = sorted(base.rglob("*")) if base.is_dir() else [base]
        found.update(
            path
            for path in walked
            if IGNORED_DIRECTORY not in path.parts and (path.is_symlink() or not path.is_dir())
        )
    return sorted(found)


@dataclasses.dataclass(frozen=True, slots=True)
class Admitted:
    relative: str
    mode: quantities.FileMode
    payload: bytes

    def entry(self) -> archives.BundledFile:
        return archives.BundledFile(
            path=self.relative, mode=self.mode, digest=hashing.digest_bytes(self.payload)
        )


def admitted(sources: archives.SourceSet, screen: archives.Screen) -> Iterator[Admitted]:
    """Each candidate read once and screened, refused when it is a link or not a file."""
    for candidate in candidates(sources):
        relative = str(candidate.relative_to(sources.root.path))
        if candidate.is_symlink():
            raise errors.Refusal(refusals.RefusalReason.PATH_IS_A_SYMLINK, subject=relative)
        if not candidate.is_file():
            raise errors.Refusal(refusals.RefusalReason.ARCHIVE_ENTRY_NOT_REGULAR, subject=relative)
        payload = candidate.read_bytes()
        mode = mode_for(candidate)
        screen(archives.BundleCandidate(path=relative, mode=mode, payload=payload))
        yield Admitted(relative=relative, mode=mode, payload=payload)
