"""The builder's development signing key, its public half fetched over the builder's own ssh.

The key that signs a development bundle must be trusted from somewhere the bundle cannot
reach: the builder answers on its authenticated channel, the host checks the bytes parse as
a public key, and the runtime root keeps them beside a record of where they came from. A
key that differs from the one already kept is refused, because rotation is reviewed and
never silent; what is kept is never release trust.
"""

from __future__ import annotations

import dataclasses

from apex.config import defaults
from apex.kernel import commands, encoding, errors, identifiers, refusals, safepaths
from apex.ports import guestshell, portset
from apex.trust import anchors

FETCH = guestshell.RemoteScript.of(
    guestshell.Step.of("test", "-f", defaults.BUILDER_MARKER),
    guestshell.Step.of("sudo", "openssl", "pkey", "-in", defaults.DEVELOPMENT_KEY_PATH, "-pubout"),
)
CHECK = commands.Argv.of("openssl", "pkey", "-pubin", "-noout")


@dataclasses.dataclass(frozen=True, slots=True)
class Retrieved:
    anchor: anchors.TrustAnchor
    digest: identifiers.Digest
    record: safepaths.SafePath

    def document(self) -> encoding.Document:
        return {
            "purpose": defaults.DEVELOPMENT_PURPOSE,
            "path": str(self.anchor.public_key.path),
            "sha256": self.digest.hex,
            "source": defaults.DEVELOPMENT_SOURCE,
            "release_trust": False,
        }


def retrieve(
    ports: portset.HostPorts, *, builder: guestshell.GuestTarget, root: safepaths.RuntimeRoot
) -> Retrieved:
    fetched = ports.guest.run(
        builder,
        guestshell.GuestRun(
            script=FETCH,
            deadline=defaults.GUEST_COMMAND_DEADLINE,
            limit=commands.OutputLimit.default(),
        ),
    )
    if not fetched.succeeded:
        raise errors.PortFailure(
            port="guest", cause="the builder did not give up its development public key"
        )
    _require_public_key(ports, fetched.stdout)
    directory = root.child(defaults.TRUST_DIRECTORY)
    ports.files.make_directory(directory, mode=safepaths.PRIVATE_DIRECTORY_MODE)
    key = directory / defaults.DEVELOPMENT_KEY_NAME
    if ports.files.exists(key):
        kept = ports.files.read_bytes(key, limit=defaults.DOCUMENT_LIMIT.value)
        if kept != fetched.stdout:
            raise errors.Refusal(
                refusals.RefusalReason.DEVELOPMENT_KEY_CHANGED,
                subject=str(key),
                remedy="review the rotation before replacing the kept key",
            )
    digest = ports.files.write_atomic(key, fetched.stdout, mode=defaults.RECORD_MODE)
    anchor = anchors.TrustAnchor(
        public_key=safepaths.RegularFile.adopt(key.path), provenance=anchors.Provenance.BUILDER_SSH
    )
    record = directory / defaults.DEVELOPMENT_RECORD_NAME
    retrieved = Retrieved(anchor=anchor, digest=digest, record=record)
    ports.files.write_atomic(
        record, encoding.canonical(retrieved.document()) + b"\n", mode=defaults.RECORD_MODE
    )
    return retrieved


def _require_public_key(ports: portset.HostPorts, pem: bytes) -> None:
    checked = ports.processes.run(
        CHECK, deadline=defaults.KEY_CHECK_DEADLINE, limit=commands.OutputLimit.default(), stdin=pem
    )
    if not checked.succeeded:
        raise errors.Refusal(
            refusals.RefusalReason.PUBLIC_KEY_MALFORMED,
            subject="the builder's answer is not a public key",
        )
