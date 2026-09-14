"""Capture the Shell before and after its shortcut, and judge that a surface opened.

The frames are compared as the older host compared them, below the top bar so a clock tick
cannot pass; the PNG of the opened surface is filed for the reviewer, the PPM frames are
judged and not filed. A change too small to be a surface is a failure of the check; two
frames that cannot be compared are a broken capture and refuse the run. The stage is told
which facts must exist first, so every probe window is dismissed before the Shell is captured.
"""

from __future__ import annotations

from typing import Any

from apex.composition import keys as composition_keys
from apex.config import defaults
from apex.kernel import encoding, errors, identifiers, verdicts
from apex.model import screens
from apex.pipeline import effects, facts, stages
from apex.ports import portset
from apex.verification import console, judging, verifykeys

KEY = verifykeys.judged("shell.surface")
BEFORE = "shell-before.ppm"
AFTER = "shell-surface.ppm"
IMAGE = "shell-surface.png"


def apply(context: stages.RunContext[portset.HostPorts]) -> stages.StageResult:
    ports = context.ports
    monitor = context.facts[verifykeys.MONITOR]
    root = context.facts[composition_keys.RUNTIME_ROOT]
    run = context.facts[composition_keys.RUN_ID]
    try:
        before = console.capture(ports, monitor, into=console.capture_into(root, run, BEFORE))
        console.press(ports, monitor, *defaults.SHELL_SHORTCUT)
        ports.clock.sleep(defaults.SHELL_SETTLE)
        after = console.capture(ports, monitor, into=console.capture_into(root, run, AFTER))
        image = console.capture(ports, monitor, into=console.capture_into(root, run, IMAGE))
        change = screens.surface_change(screens.Frame.parse(before), screens.Frame.parse(after))
        console.press(ports, monitor, defaults.ESCAPE_KEY)
    except errors.Refusal as refusal:
        return stages.Refuse(reason=refusal.reason, detail=refusal.subject)
    except errors.PortFailure as failure:
        return stages.Fail(cause=failure.cause)
    observations: encoding.Document = {
        "shortcut": list(defaults.SHELL_SHORTCUT),
        "before": BEFORE,
        "after": AFTER,
        "capture": IMAGE,
        **change.document(),
    }
    verdict = verdicts.PASSED if change.visible else verdicts.FAILED
    filed = judging.capture(image, name=IMAGE)
    return stages.Advance(facts={KEY: judging.judge(observations, verdict, extras=[filed])})


def after(*earlier: facts.FactKey[Any]) -> stages.SimpleStage[portset.HostPorts]:
    return stages.SimpleStage(
        id=identifiers.StageId("desktop.shell-surface"),
        reads=(
            verifykeys.MONITOR,
            composition_keys.RUNTIME_ROOT,
            composition_keys.RUN_ID,
            *earlier,
        ),
        writes=(KEY,),
        attests=frozenset(),
        effects=frozenset({effects.Effect.MUTATES_GUEST, effects.Effect.WRITES_RUNTIME}),
        preflight=stages.always_ready,
        apply=apply,
    )
