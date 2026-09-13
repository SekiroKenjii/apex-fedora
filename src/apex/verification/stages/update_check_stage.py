"""Check the disposable guest booted into one fixture version, after its account logged in.

The state must be the version's, the marker must name the fixture and the version, the
older critical checks must all hold, the login, the Shell and the render must each have
passed, the recovery prerequisites are read for the record, and the sentinel must be the
one the provisioning left. The login stages run first because the plan orders them so; a
guest booted into the wrong version fails here either way.
"""

from __future__ import annotations

from apex.kernel import verdicts
from apex.verification import bootcstatus, operating, updateops
from apex.verification.stages import login_stage, render_bars_stage, shell_startup_stage

STATE = "update.state"
HEALTH = "guest.state"
RECOVERY = "recovery.prerequisites"
SENTINEL = "update.sentinel"
JUDGED = (
    ("login", login_stage.KEY),
    ("shell", shell_startup_stage.KEY),
    ("render", render_bars_stage.KEY),
)


def body(operation: operating.Operation) -> str | None:
    version = operation.action[-1]
    expected = operation.image(version)
    state = operation.ask(STATE)
    operation.report["before"] = state["bootc"]
    bootcstatus.require_booted(state["bootc"], expected)
    operation.report["marker"] = state.get("marker")
    updateops.require_marker(state.get("marker"), operation.fixture, version)
    health = operation.ask(HEALTH)
    operation.report["health"] = health.get("observations")
    problem = updateops.health_problem(health.get("observations"), expected)
    if problem is not None:
        raise bootcstatus.unexpected(problem)
    for name, key in JUDGED:
        judged = operation.context.facts[key]
        operation.report[name] = judged.observations
        if judged.verdict is not verdicts.PASSED:
            raise bootcstatus.unexpected(f"the {name} did not pass")
    operation.report["recovery"] = operation.ask(RECOVERY)
    sentinel = operation.ask(SENTINEL, {"action": "verify"}, privileged=False)
    operation.report["sentinel_sha256"] = sentinel.get("sha256")
    updateops.require_sentinel(sentinel)
    return None


STAGE = operating.stage(updateops.NAME, body, after=[key for _, key in JUDGED])
