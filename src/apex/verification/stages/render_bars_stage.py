"""Show the render probe and look for its bars in the hypervisor's frame, retrying as before.

The older host pressed Escape, waited a second, captured and judged, for up to forty five
seconds, then required the journal to name a Wayland display. A window that never presents
blocks the verdict; bars that never show, or a display that is not Wayland, fail it. The
PNG of the last frame is filed for the reviewer whatever the verdict. Told which earlier
judgements it stands on, the stage blocks itself when one did not pass, without a probe.
"""

from __future__ import annotations

from collections.abc import Sequence

from apex.composition import keys as composition_keys
from apex.config import defaults
from apex.kernel import encoding, errors, identifiers, timing, verdicts
from apex.model import screens
from apex.pipeline import effects, facts, stages
from apex.ports import portset
from apex.verification import console, judging, probing, verifykeys

KEY = verifykeys.judged("render.bars")
FRAME = "application.ppm"
IMAGE = "application.png"
PRESENTED = "presented"
DISPLAY = "display_type"
CLOCK = "clock"
SETTLE = timing.Elapsed(1)


def _bars(context: stages.RunContext[portset.HostPorts]) -> screens.Bars | None:
    """Press Escape, capture, judge; repeat under the older deadline; the last judgement stays."""
    ports = context.ports
    monitor = context.facts[verifykeys.MONITOR]
    root = context.facts[composition_keys.RUNTIME_ROOT]
    run = context.facts[composition_keys.RUN_ID]
    latest: list[screens.Bars] = []

    def visible() -> bool:
        console.press(ports, monitor, defaults.ESCAPE_KEY)
        ports.clock.sleep(SETTLE)
        frame = console.capture(ports, monitor, into=console.capture_into(root, run, FRAME))
        latest.append(screens.swatches(screens.Frame.parse(frame)))
        return latest[-1].visible

    try:
        ports.clock.wait_until(visible, defaults.BARS_APPEAR)
    except errors.PortFailure as failure:
        if failure.port != CLOCK:
            raise
    return latest[-1] if latest else None


def for_case(
    case: probing.ProbeCase, *, gates: Sequence[facts.FactKey[judging.Judged]] = ()
) -> stages.SimpleStage[portset.HostPorts]:
    def apply(context: stages.RunContext[portset.HostPorts]) -> stages.StageResult:
        blocked = judging.blocked_by(context.facts, gates)
        if blocked is not None:
            return stages.Advance(facts={KEY: blocked})
        return _judged(context, case)

    return stages.SimpleStage(
        id=identifiers.StageId("desktop.render-bars"),
        reads=(
            verifykeys.GUEST, verifykeys.AGENT, verifykeys.MONITOR,
            composition_keys.RUNTIME_ROOT, composition_keys.RUN_ID, *gates,
        ),
        writes=(KEY,),
        attests=frozenset(),
        effects=frozenset({
            effects.Effect.REMOTE_EXEC, effects.Effect.MUTATES_GUEST,
            effects.Effect.WRITES_RUNTIME,
        }),
        preflight=stages.always_ready,
        apply=apply,
    )


def _judged(
    context: stages.RunContext[portset.HostPorts], case: probing.ProbeCase
) -> stages.StageResult:
    ports = context.ports
    try:
        observed = probing.observe(
            ports, context.facts[verifykeys.GUEST], context.facts[verifykeys.AGENT], case,
            token=ports.identities.token(),
        )
        presented = observed.observations.get(PRESENTED) is True
        extras = [observed.proof]
        bars = None
        if presented:
            bars = _bars(context)
            monitor = context.facts[verifykeys.MONITOR]
            image = console.capture(
                ports, monitor,
                into=console.capture_into(
                    context.facts[composition_keys.RUNTIME_ROOT],
                    context.facts[composition_keys.RUN_ID],
                    IMAGE,
                ),
            )
            extras.append(judging.capture(image, name=IMAGE))
    except errors.Refusal as refusal:
        return stages.Refuse(reason=refusal.reason, detail=refusal.subject)
    except errors.PortFailure as failure:
        return stages.Fail(cause=failure.cause)
    display = observed.observations.get(DISPLAY)
    observations: encoding.Document = {
        "capture": IMAGE if presented else None,
        "bars": bars.document() if bars is not None else None,
        "display_type": display if isinstance(display, str) else None,
        "observations": observed.observations,
    }
    if not presented:
        verdict: verdicts.Verdict = verdicts.BLOCKED
    elif bars is not None and bars.visible and display == defaults.WAYLAND_DISPLAY:
        verdict = verdicts.PASSED
    else:
        verdict = verdicts.FAILED
    return stages.Advance(facts={KEY: judging.judge(observations, verdict, extras=extras)})
