"""Write a tar whose bytes depend only on the files it contains.

Each file is read once: the bytes are hashed while they are being written, and the contract
suite asserts the read count equals the file count.
"""

from __future__ import annotations

import io
import tarfile

from apex.adapters import sourcewalk
from apex.kernel import claims, errors, hashing, refusals, safepaths
from apex.ports import archives


class TarArchives:
    environment = claims.EnvironmentKind.BUILD

    def bundle(
        self, sources: archives.SourceSet, *, into: safepaths.SafePath
    ) -> archives.SourceBundle:
        entries: list[archives.BundledFile] = []
        reads = 0
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
        ordered = tuple(sorted(entries, key=lambda entry: entry.path))
        return archives.SourceBundle(
            archive=into,
            files=ordered,
            merkle_root=hashing.merkle_root([entry.digest for entry in ordered]),
            reads=reads,
        )
