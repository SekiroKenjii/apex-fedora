"""Bundle into memory, holding the same determinism contract."""

from __future__ import annotations

from apex.adapters import sourcewalk
from apex.kernel import claims, errors, hashing, refusals, safepaths
from apex.ports import archives


class MemoryArchives:
    environment = claims.EnvironmentKind.SIMULATED

    def __init__(self) -> None:
        self.written: dict[str, tuple[str, ...]] = {}

    def bundle(
        self, sources: archives.SourceSet, *, into: safepaths.SafePath
    ) -> archives.SourceBundle:
        entries: list[archives.BundledFile] = []
        reads = 0
        for candidate in sourcewalk.candidates(sources):
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
            entries.append(
                archives.BundledFile(
                    path=relative,
                    mode=sourcewalk.mode_for(candidate),
                    digest=hashing.digest_bytes(payload),
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
