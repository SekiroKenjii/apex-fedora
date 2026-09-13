"""Bundle into memory, holding the same determinism contract.

The archive digest is taken over the canonical listing, so it is stable for the same files
and changes when any of them does, without a tar ever being written.
"""

from __future__ import annotations

from collections.abc import Mapping

from apex.adapters import sourcewalk
from apex.kernel import claims, encoding, errors, hashing, quantities, refusals, safepaths
from apex.ports import archives, files

EXTRACTED_MODE = quantities.FileMode(0o600)


class MemoryArchives(archives.ArchivePort):
    environment = claims.EnvironmentKind.SIMULATED

    def __init__(self, filesystem: files.FileSystemPort | None = None) -> None:
        self.written: dict[str, tuple[str, ...]] = {}
        self.extracted: list[tuple[safepaths.SafePath, safepaths.SafePath]] = []
        self.packed: list[tuple[safepaths.SafePath, safepaths.SafePath, str]] = []
        self.held: dict[str, dict[str, bytes]] = {}
        self.filesystem = filesystem

    def hold(self, archive: safepaths.SafePath, members: Mapping[str, bytes]) -> None:
        """Declare what an archive contains, for members and for an extraction to lay down."""
        self.held[str(archive)] = dict(members)

    def pack(self, directory: safepaths.SafePath, *, into: safepaths.SafePath, name: str) -> None:
        self.packed.append((directory, into, name))
        self.held[str(into)] = {
            f"{name}/{path.relative_to(directory.path)}": path.read_bytes()
            for path in sorted(directory.path.rglob("*"))
            if path.is_file()
        }

    def extract(self, archive: safepaths.SafePath, *, into: safepaths.SafePath) -> None:
        self.extracted.append((archive, into))
        for name, payload in self.held.get(str(archive), {}).items():
            target = safepaths.SafePath(into.path / name)
            if self.filesystem is not None:
                self.filesystem.write_atomic(target, payload, mode=EXTRACTED_MODE)
            else:
                target.path.parent.mkdir(parents=True, exist_ok=True)
                target.path.write_bytes(payload)

    def members(self, archive: safepaths.SafePath) -> tuple[str, ...]:
        if str(archive) not in self.held:
            raise errors.PortFailure(port="archives", cause=f"{archive}: no such archive")
        return tuple(self.held[str(archive)])

    def bundle(
        self, sources: archives.SourceSet, *, into: safepaths.SafePath, screen: archives.Screen
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
            mode = sourcewalk.mode_for(candidate)
            screen(archives.BundleCandidate(path=relative, mode=mode, payload=payload))
            entries.append(
                archives.BundledFile(
                    path=relative, mode=mode, digest=hashing.digest_bytes(payload)
                )
            )
        ordered = tuple(sorted(entries, key=lambda entry: entry.path))
        self.written[str(into)] = tuple(entry.path for entry in ordered)
        listing = [
            {"path": entry.path, "mode": str(entry.mode), "digest": entry.digest.hex}
            for entry in ordered
        ]
        return archives.SourceBundle(
            archive=into,
            archive_digest=hashing.digest_bytes(encoding.canonical(listing)),
            files=ordered,
            merkle_root=hashing.merkle_root([entry.digest for entry in ordered]),
            reads=reads,
        )
