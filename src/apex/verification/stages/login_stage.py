"""Log the disposable account in at GDM through the monitor, as the older host did.

The greeter is waited for and captured, Return opens the password prompt, the password is
typed as key codes and Return submits it; the account's Wayland session on the seat is the
proof that it was accepted. The password comes from the credentials the run was given and
goes nowhere else: not into an observation, not into a proof, not into a refusal. A seat
that already holds the account's session refuses the run, because a login not performed
here proves nothing; a greeter that never comes, or a session that never appears, fails
the check.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping

from apex.attestation import minting
from apex.composition import keys as composition_keys
from apex.config import defaults
from apex.kernel import encoding, errors, identifiers, refusals, secrets, verdicts
from apex.pipeline import effects, stages
from apex.ports import portset
from apex.verification import console, judging, probing, testaccess, verifykeys

KEY = verifykeys.judged("login")
IMAGE = "greeter.png"
METHOD = "GDM password through the monitor"
USER = "user"
WAIT = "wait"
FOUND = "found"
WAYLAND = "wayland"


def for_cases(
    session: probing.ProbeCase, greeter: probing.ProbeCase
) -> stages.SimpleStage[portset.HostPorts]:
    def apply(context: stages.RunContext[portset.HostPorts]) -> stages.StageResult:
        try:
            return _login(context, session, greeter, context.facts[verifykeys.CREDENTIALS])
        except errors.Refusal as refusal:
            return stages.Refuse(reason=refusal.reason, detail=refusal.subject)
        except errors.PortFailure as failure:
            return stages.Fail(cause=failure.cause)

    return stages.SimpleStage(
        id=identifiers.StageId("desktop.login"),
        reads=(
            verifykeys.GUEST, verifykeys.AGENT, verifykeys.MONITOR, verifykeys.CREDENTIALS,
            composition_keys.RUNTIME_ROOT, composition_keys.RUN_ID,
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


def _login(
    context: stages.RunContext[portset.HostPorts],
    session: probing.ProbeCase,
    greeter: probing.ProbeCase,
    credentials: testaccess.Credentials,
) -> stages.StageResult:
    console.typeable(credentials.password)
    before = _observe(context, session, {USER: credentials.user, WAIT: False})
    if before.observations.get(FOUND) is True:
        return stages.Refuse(
            reason=refusals.RefusalReason.SESSION_ALREADY_OPEN,
            detail=f"{credentials.user} already holds a session on the seat",
        )
    waited = _observe(context, greeter, {})
    proofs = [before.proof, waited.proof]
    if waited.observations.get(FOUND) is not True:
        return _advance(
            credentials.user, verdicts.FAILED, greeter=waited.observations, after=None,
            proofs=proofs,
        )
    proofs.append(_typed(context, credentials.password))
    after = _observe(context, session, {USER: credentials.user, WAIT: True})
    proofs.append(after.proof)
    accepted = after.observations.get(WAYLAND) is True
    return _advance(
        credentials.user, verdicts.PASSED if accepted else verdicts.FAILED,
        greeter=waited.observations, after=after.observations, proofs=proofs,
    )


def _observe(
    context: stages.RunContext[portset.HostPorts],
    case: probing.ProbeCase,
    arguments: Mapping[str, encoding.JsonValue],
) -> probing.Observation:
    ports = context.ports
    return probing.observe(
        ports, context.facts[verifykeys.GUEST], context.facts[verifykeys.AGENT],
        dataclasses.replace(case, arguments=dict(arguments)), token=ports.identities.token(),
    )


def _typed(
    context: stages.RunContext[portset.HostPorts], password: secrets.Secret[str]
) -> minting.Offered:
    """Settle the greeter, capture it, open the prompt, type, submit; the capture is proof."""
    ports = context.ports
    monitor = context.facts[verifykeys.MONITOR]
    ports.clock.sleep(defaults.GREETER_SETTLE)
    into = console.capture_into(
        context.facts[composition_keys.RUNTIME_ROOT], context.facts[composition_keys.RUN_ID],
        IMAGE,
    )
    image = console.capture(ports, monitor, into=into)
    console.press(ports, monitor, defaults.RETURN_KEY)
    ports.clock.sleep(defaults.PROMPT_SETTLE)
    console.type_secret(ports, monitor, password)
    console.press(ports, monitor, defaults.RETURN_KEY)
    return judging.capture(image, name=IMAGE)


def _advance(
    user: str,
    verdict: verdicts.Verdict,
    *,
    greeter: encoding.Document,
    after: encoding.Document | None,
    proofs: list[minting.Offered],
) -> stages.Advance:
    observations: encoding.Document = {
        "method": METHOD,
        "user": user,
        "capture": IMAGE if after is not None else None,
        "greeter": greeter,
        "session": after,
    }
    return stages.Advance(facts={KEY: judging.judge(observations, verdict, extras=proofs)})
