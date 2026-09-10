"""Write a tar whose bytes depend only on the files it contains.

Each file is read once. The bytes are hashed while they are being written, which is what
removes the second read the current bundler performs on every source file on every build.
"""

from __future__ import annotations

import io
import pathlib
import tarfile

from apex.kernel import claims, errors, hashing, quantities, refusals, safepaths
from apex.ports import archives

EXECUTABLE_SUFFIXES = frozenset({".sh"})
EXECUTABLE_MODE = quantities.FileMode(0o755)
ORDINARY_MODE = quantities.FileMode(0o644)
IGNORED_DIRECTORY = "__pycache__"


class TarArchives:
    environment = claims.EnvironmentKind.BUILD

    def bundle(
        self, sources: archives.SourceSet, *, into: safepaths.SafePath
    ) -> archives.SourceBundle:
        entries: list[archives.BundledFile] = []
        reads = 0
        with tarfile.open(into.path, "w") as archive:
            for candidate in self._candidates(sources):
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

    def _candidates(self, sources: archives.SourceSet) -> list[pathlib.Path]:
        found: list[pathlib.Path] = []
        for relative in sources.relative_paths:
            base = sources.root.path / relative
            if not base.exists():
                continue
            candidates = sorted(base.rglob("*")) if base.is_dir() else [base]
            found.extend(
                path
                for path in candidates
                if IGNORED_DIRECTORY not in path.parts and not path.is_dir()
            )
        return sorted(found)
