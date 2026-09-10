"""Bundle into memory, holding the same determinism contract."""

from __future__ import annotations

from apex.kernel import claims, errors, hashing, quantities, refusals, safepaths
from apex.ports import archives

EXECUTABLE_SUFFIXES = frozenset({".sh"})
EXECUTABLE_MODE = quantities.FileMode(0o755)
ORDINARY_MODE = quantities.FileMode(0o644)
IGNORED_DIRECTORY = "__pycache__"


class MemoryArchives:
    environment = claims.EnvironmentKind.SIMULATED

    def __init__(self) -> None:
        self.written: dict[str, tuple[str, ...]] = {}

    def bundle(
        self, sources: archives.SourceSet, *, into: safepaths.SafePath
    ) -> archives.SourceBundle:
        entries: list[archives.BundledFile] = []
        reads = 0
        for relative_root in sources.relative_paths:
            base = sources.root.path / relative_root
            if not base.exists():
                continue
            candidates = sorted(base.rglob("*")) if base.is_dir() else [base]
            for candidate in sorted(candidates):
                if candidate.is_dir() or IGNORED_DIRECTORY in candidate.parts:
                    continue
                relative = str(candidate.relative_to(sources.root.path))
                if candidate.is_symlink():
                    raise errors.Refusal(
                        refusals.RefusalReason.PATH_IS_A_SYMLINK, subject=relative
                    )
                if not candidate.is_file():
                    raise errors.Refusal(
                        refusals.RefusalReason.ARCHIVE_ENTRY_NOT_REGULAR, subject=relative
                    )
                payload = candidate.read_bytes()
                reads += 1
                mode = (
                    EXECUTABLE_MODE if candidate.suffix in EXECUTABLE_SUFFIXES else ORDINARY_MODE
                )
                entries.append(
                    archives.BundledFile(
                        path=relative, mode=mode, digest=hashing.digest_bytes(payload)
                    )
                )
        ordered = tuple(sorted(entries, key=lambda entry: entry.path))
        self.written[str(into)] = tuple(entry.path for entry in ordered)
        return archives.SourceBundle(
            archive=into,
            files=ordered,
            merkle_root=hashing.merkle_root([entry.digest for entry in ordered]),
            reads=reads,
        )
