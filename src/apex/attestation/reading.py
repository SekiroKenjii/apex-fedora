"""The one entry point for reading a store of any version: elect, then call."""

from __future__ import annotations

from pathlib import Path

from apex.attestation import electing, readerspecs
from apex.ports import files as files_port


def read_store(
    runtime_root: Path, *, files: files_port.FileSystemPort
) -> readerspecs.StoreReading:
    """The legacy documents are read where they lie; the chain is read through the port."""
    spec = electing.reader_for(runtime_root)
    return spec.read(runtime_root, spec=spec, files=files)
