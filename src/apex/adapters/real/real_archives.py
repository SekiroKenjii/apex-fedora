"""Write a tar whose bytes depend only on the files it contains.

Each source file is read once: the bytes are hashed while they are being written, and the
contract suite asserts the read count equals the file count. A screen refusal removes the
partial archive, so a refused bundle leaves nothing on disk.
"""

from __future__ import annotations

import io
import tarfile

from apex.adapters import sourcewalk
from apex.kernel import claims, errors, hashing, quantities, safepaths
from apex.ports import archives

PRIVATE_DIRECTORY = 0o700
ARCHIVE_MODE = quantities.FileMode(0o600)


class TarArchives(archives.ArchivePort):
    environment = claims.EnvironmentKind.BUILD

    def pack(self, directory: safepaths.SafePath, *, into: safepaths.SafePath, name: str) -> None:
        try:
            with tarfile.open(into.path, "w") as opened:
                opened.add(directory.path, arcname=name)
        except (OSError, tarfile.TarError) as error:
            raise errors.PortFailure(port="archives", cause=str(error)) from error

    def extract(self, archive: safepaths.SafePath, *, into: safepaths.SafePath) -> None:
        try:
            with tarfile.open(archive.path) as opened:
                opened.extractall(into.path, filter="data")
        except (OSError, tarfile.TarError) as error:
            raise errors.PortFailure(port="archives", cause=str(error)) from error

    def members(self, archive: safepaths.SafePath) -> tuple[str, ...]:
        try:
            with tarfile.open(archive.path) as opened:
                return tuple(opened.getnames())
        except (OSError, tarfile.TarError) as error:
            raise errors.PortFailure(port="archives", cause=str(error)) from error

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
            for admitted in sourcewalk.admitted(sources, screen):
                reads += 1
                info = tarfile.TarInfo(admitted.relative)
                info.size = len(admitted.payload)
                info.mode = admitted.mode.value
                info.mtime = 0
                archive.addfile(info, io.BytesIO(admitted.payload))
                entries.append(admitted.entry())
        return tuple(sorted(entries, key=lambda entry: entry.path)), reads
