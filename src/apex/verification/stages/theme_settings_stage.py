"""Ask the session for its theme settings and judge them against the ones the image ships.

The older host asserted the GTK theme and the Shell theme by name after its captures; the
extensions and the composition were retained. A setting the session could not report blocks
the verdict; a setting that names another theme fails it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from apex.config import defaults
from apex.kernel import encoding, errors, identifiers, verdicts
from apex.pipeline import effects, facts, stages
from apex.ports import portset
from apex.verification import judging, probing, verifykeys

KEY = verifykeys.judged("theme.settings")
EXPECTED: Mapping[str, str] = {"gtk_theme": defaults.GTK_THEME, "shell_theme": defaults.SHELL_THEME}
SETTINGS = "settings"


def verdict_of(observations: encoding.Document) -> tuple[verdicts.Verdict, dict[str, str]]:
    """The verdict and, for each expected setting, what the session said or why it could not."""
    settings = observations.get(SETTINGS)
    if not isinstance(settings, Mapping):
        return verdicts.BLOCKED, {}
    said: dict[str, str] = {}
    verdict: verdicts.Verdict = verdicts.PASSED
    for name, expected in EXPECTED.items():
        entry = settings.get(name)
        if not isinstance(entry, Mapping) or entry.get("returncode") != 0:
            return verdicts.BLOCKED, said
        stdout = entry.get("stdout")
        if not isinstance(stdout, str):
            return verdicts.BLOCKED, said
        said[name] = stdout.strip()
        if said[name] != expected:
            verdict = verdicts.FAILED
    return verdict, said


def for_case(
    case: probing.ProbeCase, *, after: Sequence[facts.FactKey[Any]] = ()
) -> stages.SimpleStage[portset.HostPorts]:
    def apply(context: stages.RunContext[portset.HostPorts]) -> stages.StageResult:
        ports = context.ports
        try:
            observed = probing.observe(
                ports, context.facts[verifykeys.GUEST], context.facts[verifykeys.AGENT], case,
                token=ports.identities.token(),
            )
        except errors.Refusal as refusal:
            return stages.Refuse(reason=refusal.reason, detail=refusal.subject)
        except errors.PortFailure as failure:
            return stages.Fail(cause=failure.cause)
        verdict, said = verdict_of(observed.observations)
        observations: encoding.Document = {
            "expected": dict(EXPECTED),
            "reported": said,
            "observations": observed.observations,
        }
        return stages.Advance(
            facts={KEY: judging.judge(observations, verdict, extras=[observed.proof])}
        )

    return stages.SimpleStage(
        id=identifiers.StageId(str(case.unit)),
        reads=(verifykeys.GUEST, verifykeys.AGENT, *after),
        writes=(KEY,),
        attests=frozenset(),
        effects=frozenset({effects.Effect.REMOTE_EXEC}),
        preflight=stages.always_ready,
        apply=apply,
    )
