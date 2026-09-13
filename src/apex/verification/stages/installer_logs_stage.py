"""The three installer logs must have come whole, or the run fails naming the first that did not.

The older collection exited non-zero on an incomplete bundle so the operator would not
cancel the installer before its logs existed; this stage does the same after the bundle
is kept, so what did arrive is never lost.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
from collections.abc import Mapping

from apex.kernel import identifiers
from apex.pipeline import stages
from apex.ports import portset
from apex.verification import probing, verifykeys

REQUIRED = ("anaconda.log", "storage.log", "program.log")


def _incomplete(item: object) -> str | None:
    """Why one log is not whole, or nothing when it is."""
    if not isinstance(item, Mapping):
        return "absent"
    if "error" in item:
        return str(item["error"])
    if item.get("truncated") is not False:
        return "truncated"
    try:
        data = base64.b64decode(str(item.get("data", "")), validate=True)
    except (binascii.Error, ValueError):
        return "not base64"
    if hashlib.sha256(data).hexdigest() != item.get("sha256"):
        return "checksum mismatch"
    return None


def for_case(case: probing.ProbeCase) -> stages.SimpleStage[portset.HostPorts]:
    observed = verifykeys.observed(case)

    def apply(context: stages.RunContext[portset.HostPorts]) -> stages.StageResult:
        logs = context.facts[observed].observations.get("logs")
        held: Mapping[str, object] = logs if isinstance(logs, Mapping) else {}
        for name in REQUIRED:
            why = _incomplete(held.get(name))
            if why is not None:
                return stages.Fail(cause=f"{name} {why}; do not cancel the installer yet")
        return stages.Advance(facts={verifykeys.LOGS_COMPLETE: True})

    return stages.SimpleStage(
        id=identifiers.StageId("installer.logs"),
        reads=(observed, verifykeys.retained_observation(case)),
        writes=(verifykeys.LOGS_COMPLETE,),
        attests=frozenset(),
        effects=frozenset(),
        preflight=stages.always_ready,
        apply=apply,
    )
