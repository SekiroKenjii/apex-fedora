"""What every guest operation stage shares: root through the account, a report, an ending.

The disposable guest is reached as its account and every privileged unit runs through sudo
with the account's password on the line before the request. Each request and its answer
go into the run's report, which is written under the run's exports whether the operation
ended in a pass, a refusal or a failure, as the older tools kept their results files.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from apex.composition import agentrun, exports
from apex.composition import keys as composition_keys
from apex.config import defaults
from apex.kernel import encoding, errors, identifiers, safepaths
from apex.pipeline import effects, facts, stages
from apex.ports import portset
from apex.verification import updatefixtures, verifykeys

STATUS = "status"
PASS = "PASS"
FAIL = "FAIL"
Body = Callable[["Operation"], str | None]


@dataclasses.dataclass(frozen=True, slots=True)
class Operation:
    """One run's view of the guest: what to do, against which fixture, reported where."""

    context: stages.RunContext[portset.HostPorts]
    located: updatefixtures.Located
    action: str
    report: dict[str, encoding.JsonValue]

    @property
    def fixture(self) -> str:
        return str(self.located.report.run)

    @property
    def images(self) -> dict[str, encoding.JsonValue]:
        return {v: str(image.digest) for v, image in self.located.report.images.items()}

    def image(self, version: str) -> str:
        return str(self.located.report.images[version].digest)

    def ask(
        self,
        unit: str,
        arguments: Mapping[str, encoding.JsonValue] | None = None,
        *,
        privileged: bool = True,
        private_mounts: bool = False,
    ) -> encoding.Document:
        """One unit asked, as root through the account's password unless it is the account's."""
        ports = self.context.ports
        credentials = self.context.facts[verifykeys.CREDENTIALS]
        given = dict(arguments or {})
        reply = agentrun.run_unit(
            ports,
            self.context.facts[verifykeys.GUEST],
            self.context.facts[verifykeys.AGENT],
            unit=identifiers.ProbeId(unit),
            arguments=given,
            token=ports.identities.token(),
            privileged=privileged,
            password=credentials.password if privileged else None,
            private_mounts=private_mounts,
        )
        asked = self.report.setdefault("requests", [])
        if isinstance(asked, list):
            asked.append({"unit": unit, "arguments": given, "observations": reply.observations})
        return reply.observations


def _write(operation: Operation, name: str) -> safepaths.SafePath:
    target = exports.inside(
        operation.context.facts[composition_keys.RUNTIME_ROOT],
        operation.context.facts[composition_keys.RUN_ID],
        f"{name}.json",
    )
    operation.context.ports.files.write_atomic(
        target, encoding.canonical(operation.report) + b"\n", mode=defaults.RECORD_MODE
    )
    return target


def run(context: stages.RunContext[portset.HostPorts], name: str, body: Body) -> stages.StageResult:
    """The body over a fresh report; the report is kept however the body ends."""
    located = context.facts[verifykeys.FIXTURE]
    operation = Operation(
        context=context,
        located=located,
        action=context.facts[verifykeys.ACTION],
        report={
            STATUS: FAIL,
            "action": context.facts[verifykeys.ACTION],
            "fixture": str(located.report.run),
            "images": {v: str(i.digest) for v, i in located.report.images.items()},
            "machine_process": context.facts[verifykeys.MACHINE_PROCESS],
        },
    )
    try:
        operation.report[STATUS] = body(operation) or PASS
    except errors.Refusal as refusal:
        operation.report["failure"] = f"{refusal.reason}: {refusal.subject}"
        _write(operation, name)
        return stages.Refuse(reason=refusal.reason, detail=refusal.subject)
    except errors.PortFailure as failure:
        operation.report["failure"] = failure.cause
        _write(operation, name)
        return stages.Fail(cause=failure.cause)
    kept = _write(operation, name)
    return stages.Advance(
        facts={
            verifykeys.test_report(name): operation.report,
            verifykeys.retained_report(name): kept,
        }
    )


READS: tuple[facts.FactKey[Any], ...] = (
    verifykeys.GUEST,
    verifykeys.AGENT,
    verifykeys.FIXTURE,
    verifykeys.ACTION,
    verifykeys.CREDENTIALS,
    verifykeys.MACHINE_PROCESS,
    composition_keys.RUNTIME_ROOT,
    composition_keys.RUN_ID,
)


def stage(
    name: str, body: Body, *, after: Sequence[facts.FactKey[Any]] = ()
) -> stages.SimpleStage[portset.HostPorts]:
    """One operation stage, named for its family, reading what every operation reads."""
    return stages.SimpleStage(
        id=identifiers.StageId(f"{name}.operate"),
        reads=(*READS, *after),
        writes=(verifykeys.test_report(name), verifykeys.retained_report(name)),
        attests=frozenset(),
        effects=frozenset(
            {
                effects.Effect.REMOTE_EXEC,
                effects.Effect.MUTATES_GUEST,
                effects.Effect.WRITES_RUNTIME,
            }
        ),
        preflight=stages.always_ready,
        apply=lambda context: run(context, name, body),
    )
