"""Select a verified image build as the candidate under test, keeping the previous one.

A candidate is selected for testing and never approved by this; the readiness fold decides
that. The previous candidate's document is archived under its own run so the reader can
say what was under test before. The store is not touched: every record names the digest
it was made for, so a record of the previous candidate stays attributed to it.
"""

from __future__ import annotations

import dataclasses
import json

from apex.config import defaults
from apex.kernel import encoding, errors, identifiers, refusals, safepaths
from apex.model import runtimestate
from apex.ports import portset

NOTE = "Candidate selected for testing, not approved for installation"


@dataclasses.dataclass(frozen=True, slots=True)
class Selected:
    digest: identifiers.Digest
    build: identifiers.BuildId
    previous: identifiers.Digest | None
    archived: safepaths.SafePath | None

    def document(self) -> encoding.Document:
        return {
            "selected": {"digest": str(self.digest), "build_id": str(self.build)},
            "previous": None if self.previous is None else str(self.previous),
            "archived": None if self.archived is None else str(self.archived),
            "note": NOTE,
        }


def select(
    ports: portset.HostPorts,
    *,
    root: safepaths.RuntimeRoot,
    digest: identifiers.Digest,
    build: identifiers.BuildId,
    verification: encoding.Document,
    run: identifiers.RunId,
) -> Selected:
    target = root.child(runtimestate.CANDIDATE_NAME)
    previous = _previous(ports, target)
    archived = None
    if previous is not None and previous != digest:
        archive = root.child(f"{defaults.CANDIDATE_HISTORY_DIRECTORY}/{run}")
        ports.files.make_directory(archive, mode=safepaths.PRIVATE_DIRECTORY_MODE)
        archived = archive / runtimestate.CANDIDATE_NAME
        ports.files.copy(target, archived)
    document: encoding.Document = {
        "digest": str(digest), "build_id": str(build), "verification": verification,
    }
    ports.files.write_atomic(
        target, encoding.canonical(document) + b"\n", mode=defaults.RECORD_MODE
    )
    return Selected(digest=digest, build=build, previous=previous, archived=archived)


def _previous(ports: portset.HostPorts, target: safepaths.SafePath) -> identifiers.Digest | None:
    if not ports.files.exists(target):
        return None
    try:
        loaded = json.loads(ports.files.read_bytes(target, limit=defaults.DOCUMENT_LIMIT.value))
        return identifiers.Digest.parse(str(loaded["digest"]))
    except (json.JSONDecodeError, KeyError, TypeError) as fault:
        raise errors.Refusal(
            refusals.RefusalReason.MALFORMED_IDENTIFIER,
            subject=f"{target.path.name}: {fault}",
            remedy="the candidate document on disk is not one this tool wrote",
        ) from fault
