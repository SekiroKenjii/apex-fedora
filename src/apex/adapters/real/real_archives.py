"""Write a tar whose bytes depend only on the files it contains.

Each source file is read once: the bytes are hashed while they are being written, and the
contract suite asserts the read count equals the file count. A screen refusal removes the
partial archive, so a refused bundle leaves nothing on disk.
"""

from __future__ import annotations

import io
import tarfile

from apex.adapters import sourcewalk
from apex.kernel import claims, errors, hashing, quantities, refusals, safepaths
from apex.ports import archives

PRIVATE_DIRECTORY = 0o700
ARCHIVE_MODE = quantities.FileMode(0o600)


class TarArchives(archives.ArchivePort):
    environment = claims.EnvironmentKind.BUILD

    def bundle(
        self, sources: archives.SourceSet, *, into: safepaths.SafePath, screen: archives.Screen
    ) -> archives.SourceBundle:
        try:
            entries, reads = self._write(sources, into=into, screen=screen)
        except errors.ApexError:
            into.path.unlink(missing_ok=True)
            raise
        into.path.chmod(ARCHIVE_MODE.value)
        with into.path.open("rb") as handle:
            archive_digest = hashing.digest_stream(
                iter(lambda: handle.read(hashing.READ_CHUNK), b"")
            )
        return archives.SourceBundle(
            archive=into,
            archive_digest=archive_digest,
            files=entries,
            merkle_root=hashing.merkle_root([entry.digest for entry in entries]),
            reads=reads,
        )

    def _write(
        self, sources: archives.SourceSet, *, into: safepaths.SafePath, screen: archives.Screen
    ) -> tuple[tuple[archives.BundledFile, ...], int]:
        entries: list[archives.BundledFile] = []
        reads = 0
        into.path.parent.mkdir(parents=True, exist_ok=True, mode=PRIVATE_DIRECTORY)
        with tarfile.open(into.path, "w") as archive:
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
                info = tarfile.TarInfo(relative)
                info.size = len(payload)
                info.mode = mode.value
                info.mtime = 0
                archive.addfile(info, io.BytesIO(payload))
                entries.append(
                    archives.BundledFile(
                        path=relative, mode=mode, digest=hashing.digest_bytes(payload)
                    )
                )
        return tuple(sorted(entries, key=lambda entry: entry.path)), reads
