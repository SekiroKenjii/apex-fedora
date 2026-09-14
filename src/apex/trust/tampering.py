"""Building a deliberately broken copy of a bundle for a negative to verify against.

Only the two header documents are ever copied. Payloads can be large, and a negative that
needs one writes a small stand-in instead, which is enough because the verifier refuses at
the first mismatch in inventory order.
"""

from __future__ import annotations

from apex.config import defaults
from apex.kernel import quantities
from apex.model import bundles
from apex.ports import portset
from apex.trust import verifying

HEADER_MODE = quantities.FileMode(0o600)


def copy_entry(
    ports: portset.HostPorts,
    *,
    source: verifying.BundleLocation,
    target: verifying.BundleLocation,
    name: str,
) -> bytes:
    payload = ports.files.read_bytes(
        source.regular_entry(name), limit=defaults.DOCUMENT_LIMIT.value
    )
    ports.files.write_atomic(target.entry(name), payload, mode=HEADER_MODE)
    return payload


def copy_headers(
    ports: portset.HostPorts, *, source: verifying.BundleLocation, target: verifying.BundleLocation
) -> bytes:
    manifest = copy_entry(ports, source=source, target=target, name=bundles.MANIFEST_NAME)
    copy_entry(ports, source=source, target=target, name=bundles.SIGNATURE_NAME)
    return manifest


def write_entry(
    ports: portset.HostPorts, *, target: verifying.BundleLocation, name: str, payload: bytes
) -> None:
    ports.files.write_atomic(target.entry(name), payload, mode=HEADER_MODE)
