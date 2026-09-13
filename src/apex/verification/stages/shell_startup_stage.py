"""Wait for the Shell to finish starting, dismiss Welcome, and round-trip the Overview by key.

The older host waited for the Shell's startup event on the account's bus, captured the
first frame, sent Escape twice for Welcome's Skip, then opened the Overview with the Super
key, captured it and closed it again, reading the Overview's state over the bus after each
key and never changing it that way. A Shell that never reports startup fails the check, and
so does an Overview that does not follow a key; the round trip stops at the first key the
Shell did not follow. A login that did not pass blocks this stage without touching the guest.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping, Sequence

from apex.attestation import minting
from apex.composition import keys as composition_keys
from apex.config import defaults
from apex.kernel import encoding, errors, verdicts
from apex.pipeline import facts, stages
from apex.ports import portset
from apex.verification import console, desktopstages, judging, probing, verifykeys

KEY = verifykeys.judged("shell.startup")
STARTUP = "shell-startup.png"
OVERVIEW = "overview.png"
WELCOME_ACTION = "Escape after Shell startup"
BUS_USE = "read-only state verification"
FOUND = "found"
REACHED = "reached"
EXPECTED = "expected"
ROUNDTRIP: tuple[tuple[str | None, bool], ...] = (
    (None, False),
    (defaults.OVERVIEW_KEY, True),
    (defaults.ESCAPE_KEY, False),
)


def for_cases(
    startup: probing.ProbeCase,
    overview: probing.ProbeCase,
    *,
    gates: Sequence[facts.FactKey[judging.Judged]] = (),
) -> stages.SimpleStage[portset.HostPorts]:
    def apply(context: stages.RunContext[portset.HostPorts]) -> stages.StageResult:
        blocked = judging.blocked_by(context.facts, gates)
        if blocked is not None:
            return stages.Advance(facts={KEY: blocked})
        try:
            return _prepare(context, startup, overview)
        except errors.Refusal as refusal:
            return stages.Refuse(reason=refusal.reason, detail=refusal.subject)
        except errors.PortFailure as failure:
            return stages.Fail(cause=failure.cause)

    return desktopstages.stage("desktop.shell-startup", KEY, apply, reads=gates)


def _prepare(
    context: stages.RunContext[portset.HostPorts],
    startup: probing.ProbeCase,
    overview: probing.ProbeCase,
) -> stages.Advance:
    ports = context.ports
    monitor = context.facts[verifykeys.MONITOR]
    started = _observe(context, startup, {})
    proofs = [started.proof]
    if started.observations.get(FOUND) is not True:
        return _advance(verdicts.FAILED, startup=started.observations, followed=[], proofs=proofs)
    ports.clock.sleep(defaults.WELCOME_SETTLE)
    proofs.append(_captured(context, STARTUP))
    console.press(ports, monitor, defaults.ESCAPE_KEY)
    ports.clock.sleep(defaults.WELCOME_SETTLE)
    console.press(ports, monitor, defaults.ESCAPE_KEY)
    followed = _roundtrip(context, overview, proofs)
    passed = len(followed) == len(ROUNDTRIP) and all(followed)
    return _advance(
        verdicts.PASSED if passed else verdicts.FAILED,
        startup=started.observations,
        followed=followed,
        proofs=proofs,
    )


def _roundtrip(
    context: stages.RunContext[portset.HostPorts],
    overview: probing.ProbeCase,
    proofs: list[minting.Offered],
) -> list[bool]:
    """Closed, opened by the Super key and captured, closed by Escape; stops where it fails."""
    ports = context.ports
    monitor = context.facts[verifykeys.MONITOR]
    followed: list[bool] = []
    for key, expected in ROUNDTRIP:
        if key is not None:
            console.press(ports, monitor, key)
        step = _observe(context, overview, {EXPECTED: expected})
        proofs.append(step.proof)
        followed.append(step.observations.get(REACHED) is True)
        if not followed[-1]:
            break
        if expected:
            proofs.append(_captured(context, OVERVIEW))
    return followed


def _observe(
    context: stages.RunContext[portset.HostPorts],
    case: probing.ProbeCase,
    arguments: Mapping[str, encoding.JsonValue],
) -> probing.Observation:
    ports = context.ports
    return probing.observe(
        ports,
        context.facts[verifykeys.GUEST],
        context.facts[verifykeys.AGENT],
        dataclasses.replace(case, arguments=dict(arguments)),
        token=ports.identities.token(),
    )


def _captured(context: stages.RunContext[portset.HostPorts], name: str) -> minting.Offered:
    into = console.capture_into(
        context.facts[composition_keys.RUNTIME_ROOT], context.facts[composition_keys.RUN_ID], name
    )
    image = console.capture(context.ports, context.facts[verifykeys.MONITOR], into=into)
    return judging.capture(image, name=name)


def _advance(
    verdict: verdicts.Verdict,
    *,
    startup: encoding.Document,
    followed: list[bool],
    proofs: list[minting.Offered],
) -> stages.Advance:
    observations: encoding.Document = {
        "startup": startup,
        "welcome_action": WELCOME_ACTION,
        "overview_keyboard_roundtrip": followed,
        "dbus_used_for": BUS_USE,
        "captures": [STARTUP, *([OVERVIEW] if len(followed) > 1 and followed[1] else [])]
        if startup.get(FOUND) is True
        else [],
    }
    return stages.Advance(facts={KEY: judging.judge(observations, verdict, extras=proofs)})
