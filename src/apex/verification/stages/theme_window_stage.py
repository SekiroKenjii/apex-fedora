"""Show one theme window, capture it once it stands, and stop it: the older host's loop.

One stage per mode, made here rather than declared, because the shape is the same for GTK3
and libadwaita and only the case differs. A stage may be told which facts must exist first,
so one window is shown at a time. A window that never presents blocks the verdict
with the guest's journal as its proof; a window that presents is settled, sent Escape, captured
as PNG for the reviewer, and dismissed. The capture is filed, never judged: the older host
retained these for a visual review it did not perform.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from apex.composition import agentrun
from apex.composition import keys as composition_keys
from apex.config import defaults
from apex.kernel import encoding, errors, identifiers, verdicts
from apex.pipeline import effects, facts, stages
from apex.ports import portset
from apex.verification import console, judging, probing, verifykeys

NOT_TESTED = "NOT TESTED"
DISMISS = {"action": "dismiss"}
PRESENTED = "presented"


def for_mode(
    case: probing.ProbeCase, mode: str, *, after: Sequence[facts.FactKey[Any]] = ()
) -> stages.SimpleStage[portset.HostPorts]:
    key = verifykeys.judged(f"window.{mode}")
    name = f"{mode}.png"

    def apply(context: stages.RunContext[portset.HostPorts]) -> stages.StageResult:
        ports = context.ports
        guest, install = context.facts[verifykeys.GUEST], context.facts[verifykeys.AGENT]
        try:
            observed = probing.observe(ports, guest, install, case, token=ports.identities.token())
            presented = observed.observations.get(PRESENTED) is True
            extras = [observed.proof]
            if presented:
                ports.clock.sleep(defaults.WINDOW_SETTLE)
                monitor = context.facts[verifykeys.MONITOR]
                console.press(ports, monitor, defaults.ESCAPE_KEY)
                into = console.capture_into(
                    context.facts[composition_keys.RUNTIME_ROOT],
                    context.facts[composition_keys.RUN_ID],
                    name,
                )
                image = console.capture(ports, monitor, into=into)
                extras.append(judging.capture(image, name=name))
                agentrun.run_unit(
                    ports,
                    guest,
                    install,
                    unit=case.unit,
                    arguments=DISMISS,
                    token=ports.identities.token(),
                    privileged=case.privileged,
                )
        except errors.Refusal as refusal:
            return stages.Refuse(reason=refusal.reason, detail=refusal.subject)
        except errors.PortFailure as failure:
            return stages.Fail(cause=failure.cause)
        observations: encoding.Document = {
            "mode": mode,
            "capture": name if presented else None,
            "visual_review": NOT_TESTED,
            "observations": observed.observations,
        }
        verdict = verdicts.PASSED if presented else verdicts.BLOCKED
        return stages.Advance(facts={key: judging.judge(observations, verdict, extras=extras)})

    return stages.SimpleStage(
        id=identifiers.StageId(f"desktop.window-{mode}"),
        reads=(
            verifykeys.GUEST,
            verifykeys.AGENT,
            verifykeys.MONITOR,
            composition_keys.RUNTIME_ROOT,
            composition_keys.RUN_ID,
            *after,
        ),
        writes=(key,),
        attests=frozenset(),
        effects=frozenset(
            {
                effects.Effect.REMOTE_EXEC,
                effects.Effect.MUTATES_GUEST,
                effects.Effect.WRITES_RUNTIME,
            }
        ),
        preflight=stages.always_ready,
        apply=apply,
    )
