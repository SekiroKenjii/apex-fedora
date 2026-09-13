"""An in-memory file port whose writes also land on the disk, where the digest port reads."""

from __future__ import annotations

from apex.adapters.fakes import fake_files
from apex.kernel import identifiers, quantities, safepaths


class MirroredFiles(fake_files.MemoryFiles):
    """The memory fake, with every written or copied file laid down on the disk too."""

    def write_atomic(
        self, path: safepaths.SafePath, payload: bytes, *, mode: quantities.FileMode
    ) -> identifiers.Digest:
        path.path.parent.mkdir(parents=True, exist_ok=True)
        path.path.write_bytes(payload)
        return super().write_atomic(path, payload, mode=mode)

    def copy(self, source: safepaths.SafePath, destination: safepaths.SafePath) -> None:
        super().copy(source, destination)
        destination.path.parent.mkdir(parents=True, exist_ok=True)
        destination.path.write_bytes(self.read_bytes(source, limit=1 << 30))

    def adopt(self, path: safepaths.SafePath) -> None:
        """Take a file already on the disk into the memory tree, with its bytes."""
        super().write_atomic(path, path.path.read_bytes(), mode=quantities.FileMode(0o600))
