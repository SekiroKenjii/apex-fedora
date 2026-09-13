"""Lay a test's inputs out in the builder, run it, bring its output home and judge the report.

The two fingerprint tests that run in the builder share one shape: the host decides what
to send and where, the guest runs one program under a lock of its own with the transcript
kept on the host, the output directory comes home, and the report in it is judged by a
rule the recipe supplies. The report and the host's verdict are kept under the run's
exports, and nothing is minted.
"""

from __future__ import annotations

import dataclasses
import posixpath
from collections.abc import Callable, Mapping

from apex.composition import exports
from apex.composition import keys as composition_keys
from apex.config import defaults
from apex.kernel import commands, encoding, errors, identifiers, safepaths, timing
from apex.pipeline import effects, stages
from apex.ports import guestshell, portset
from apex.verification import judging, verifykeys

PASS = "PASS"
FAIL = "FAIL"


@dataclasses.dataclass(frozen=True, slots=True)
class BuilderTest:
    remote: safepaths.RemotePath
    deliveries: tuple[tuple[safepaths.SafePath, safepaths.RemotePath], ...]
    script: guestshell.RemoteScript
    transcript: str
    inputs: Mapping[str, str]


Prepare = Callable[[stages.RunContext[portset.HostPorts]], BuilderTest]
Judge = Callable[
    [portset.HostPorts, safepaths.RuntimeRoot, safepaths.SafePath, BuilderTest, encoding.Document],
    str | None,
]


def _run(
    context: stages.RunContext[portset.HostPorts],
    script: guestshell.RemoteScript,
    *,
    transcript: safepaths.SafePath | None = None,
    deadline: timing.Deadline = defaults.GUEST_COMMAND_DEADLINE,
) -> commands.CompletedRun:
    return context.ports.guest.run(
        context.facts[verifykeys.GUEST],
        guestshell.GuestRun(
            script=script, deadline=deadline, limit=commands.OutputLimit.default(),
            transcript=transcript,
        ),
    )


def _deliver(context: stages.RunContext[portset.HostPorts], test: BuilderTest) -> None:
    directories = sorted({posixpath.dirname(str(target)) for _, target in test.deliveries})
    made = _run(context, guestshell.RemoteScript.of(guestshell.Step.of(
        "mkdir", "-p", "-m", defaults.REMOTE_DIRECTORY_MODE, str(test.remote), *directories
    )))
    if not made.succeeded:
        raise errors.PortFailure(port="guest", cause=f"the guest could not create {test.remote}")
    for local, target in test.deliveries:
        context.ports.guest.send(
            context.facts[verifykeys.GUEST], local=local, remote=target,
            deadline=defaults.TRANSFER_DEADLINE,
        )


def _retrieve(
    context: stages.RunContext[portset.HostPorts], test: BuilderTest
) -> safepaths.SafePath:
    root = context.facts[composition_keys.RUNTIME_ROOT]
    run = context.facts[composition_keys.RUN_ID]
    output = test.remote.joined(exports.OUTPUT)
    _run(context, guestshell.RemoteScript.of(guestshell.Step(
        commands.Argv.of("sudo", "chown", "-R", defaults.BUILDER_OWNER, str(output)),
        quiet_errors=True, tolerated=True,
    )))
    context.ports.guest.receive(
        context.facts[verifykeys.GUEST], remote=output, into=exports.directory(root, run),
        recursive=True, deadline=defaults.TRANSFER_DEADLINE,
    )
    return exports.inside(root, run, exports.OUTPUT)


def for_test(name: str, *, prepare: Prepare, judge: Judge) -> stages.SimpleStage[portset.HostPorts]:
    key = verifykeys.test_report(name)
    retained = verifykeys.retained_report(name)

    def apply(context: stages.RunContext[portset.HostPorts]) -> stages.StageResult:
        root = context.facts[composition_keys.RUNTIME_ROOT]
        run = context.facts[composition_keys.RUN_ID]
        try:
            test = prepare(context)
            _deliver(context, test)
            completed = _run(
                context, test.script, transcript=exports.inside(root, run, test.transcript),
                deadline=defaults.BUILD_DEADLINE,
            )
            home = _retrieve(context, test)
            document = encoding.parse_object(context.ports.files.read_bytes(
                home / defaults.RESULTS_NAME, limit=defaults.DOCUMENT_LIMIT.value
            ))
        except errors.Refusal as refusal:
            return stages.Refuse(reason=refusal.reason, detail=refusal.subject)
        except (errors.PortFailure, ValueError) as failure:
            return stages.Fail(cause=str(failure))
        why = judge(context.ports, root, home, test, document)
        verdict = PASS if completed.succeeded and why is None else FAIL
        kept: encoding.Document = {
            **document, judging.VERDICT: verdict, "reason": why or "",
            "returncode": completed.exit_code, "inputs_sent": dict(test.inputs),
        }
        target = exports.inside(root, run, f"{name}{judging.REPORT_KIND}")
        context.ports.files.write_atomic(
            target, encoding.canonical(kept) + b"\n", mode=defaults.RECORD_MODE
        )
        if verdict != PASS:
            return stages.Fail(cause=why or f"the guest test exited with {completed.exit_code}")
        return stages.Advance(facts={key: kept, retained: target})

    return stages.SimpleStage(
        id=identifiers.StageId(f"test.{name}"),
        reads=(
            verifykeys.GUEST, verifykeys.PARENT, composition_keys.REPOSITORY,
            composition_keys.RUNTIME_ROOT, composition_keys.RUN_ID,
        ),
        writes=(key, retained),
        attests=frozenset(),
        effects=frozenset({effects.Effect.REMOTE_EXEC, effects.Effect.WRITES_RUNTIME}),
        preflight=stages.always_ready,
        apply=apply,
    )
