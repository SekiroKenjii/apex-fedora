"""The facts the verification stages pass to one another, keyed so the reader knows the type.

The run identifier and the runtime root are the composition context's keys, because they
name the same things here; nothing is renamed to look local.
"""

from __future__ import annotations

from apex.composition import agentrun
from apex.kernel import claims, identifiers, safepaths
from apex.pipeline import facts
from apex.ports import guestshell
from apex.verification import faulting, judging, recording, testaccess

GUEST = facts.FactKey[guestshell.GuestTarget]("verification.guest")
WHEEL = facts.FactKey[safepaths.SafePath]("agent.wheel")
AGENT = facts.FactKey[agentrun.AgentInstall]("agent.install")
CANDIDATE = facts.FactKey[identifiers.Digest]("candidate.digest")
WITNESS = facts.FactKey[claims.EnvironmentKind]("guest.witness")
RECORDER = facts.FactKey[recording.Recorder]("evidence.recorder")
MONITOR = facts.FactKey[safepaths.SafePath]("machine.monitor")
CREDENTIALS = facts.FactKey[testaccess.Credentials]("verification.credentials")


def fault_report(case: faulting.FaultCase) -> facts.FactKey[faulting.FaultReport]:
    return facts.FactKey[faulting.FaultReport](f"fault.{case.unit}")


def judged(name: str) -> facts.FactKey[judging.Judged]:
    return facts.FactKey[judging.Judged](f"judged.{name}")


def minted(check: identifiers.CheckId) -> facts.FactKey[recording.Recorded]:
    return facts.FactKey[recording.Recorded](f"minted.{check}")
