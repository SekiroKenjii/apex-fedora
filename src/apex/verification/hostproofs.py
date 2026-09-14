"""A proof made on the host itself, recorded with the host bundle as its witness.

A run's stage records through the recorder it was seeded with; a host proof has no run, so
it opens the store itself, judges its observations, and files the judged report as the one
proof. The witness is the bundle's own environment: a fake anywhere in it makes the proof
simulated, and the mint refuses it before anything is filed.
"""

from __future__ import annotations

from apex.kernel import encoding, identifiers, safepaths, verdicts
from apex.ports import portset
from apex.verification import judging, recording


class Minter:
    """The store a host proof is recorded into, bound to one candidate and one witness."""

    def __init__(
        self, ports: portset.HostPorts, root: safepaths.RuntimeRoot, candidate: identifiers.Digest
    ) -> None:
        self.ports = ports
        self.candidate = candidate
        self.recorder = recording.Recorder.open(
            root, filesystem=ports.files, identities=ports.identities, clock=ports.clock
        )

    def mint(
        self, check: identifiers.CheckId, verdict: verdicts.Verdict, observations: encoding.Document
    ) -> encoding.Document:
        judged = judging.judge(observations, verdict)
        recorded = self.recorder.record(
            check=check,
            verdict=verdict,
            offered=[judged.proof],
            candidate=self.candidate,
            witnessed=self.ports.environment,
        )
        return {
            "check": str(recorded.check),
            "verdict": recorded.verdict.stored_name,
            "sequence": recorded.sequence,
            "proofs": [digest.hex for digest in recorded.proofs],
        }
