"""The one entry point for reading a store of any version: elect, then call."""

from __future__ import annotations

from pathlib import Path

from apex.attestation import electing, readerspecs


def read_store(runtime_root: Path) -> readerspecs.StoreReading:
    spec = electing.reader_for(runtime_root)
    return spec.read(runtime_root, spec=spec)
