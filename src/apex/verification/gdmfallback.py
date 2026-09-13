"""Evaluate a collected recovery journal for the two-failure GDM fallback, boot by boot.

This is the older `recovery.py` evaluator over the same journal: the observer's records
are read back out of the journal lines, each failed boot of B must show the injected exit,
the production health check's rejection and the armed GRUB state, the fallback boot of A
must pass its real health check, the final failed boot must carry greenboot's rollback,
and the persistent counter must have counted down. Anything short of that is BLOCKED,
never a pass and never a fail, because it is missing evidence and not a verdict.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Mapping

from apex.kernel import encoding, errors, refusals

PREFIX = "APEX_RECOVERY_OBSERVATION "
HEALTH_BEFORE = "health-before"
GDM_START = "gdm-start"
GDM_FAILED = "ActiveState=failed\n"
GDM_ACTIVE = "ActiveState=active\n"
INJECTED_EXIT = "gdm.service: Control process exited, code=exited, status=42/"
HEALTH_REJECTED = "required script /usr/lib/greenboot/check/required.d/20-apex-system.sh failed!"
HEALTH_PASSED = "greenboot health-check passed."
ROLLED_BACK = "Rollback successful"
PASS = "PASS"
FAIL = "FAIL"
BLOCKED = "BLOCKED"
SCOPE = "Instrumented VM fixture; desktop, TTY and data need separate proof"
TWO_FAILURES = 2


class Incomplete(Exception):
    """The journal does not carry the evidence; the evaluation is BLOCKED with this reason."""


@dataclasses.dataclass(frozen=True, slots=True)
class Observation:
    boot: str
    phase: str
    digest: str
    injected: bool
    gdm_stdout: str
    grubenv: dict[str, str]

    @classmethod
    def parse(cls, message: str, boot: str) -> Observation:
        data = json.loads(message.removeprefix(PREFIX))
        if str(data["boot_id"]).replace("-", "") != boot:
            raise Incomplete("observer and journal boot identities differ")
        grubenv = str(data["grubenv"]["stdout"])
        return cls(
            boot=boot,
            phase=str(data["phase"]),
            digest=str(data["digest"]),
            injected=data.get("injected") is True,
            gdm_stdout=str(data["gdm"]["stdout"]),
            grubenv=dict(line.split("=", 1) for line in grubenv.splitlines() if "=" in line),
        )


@dataclasses.dataclass(frozen=True, slots=True)
class Journal:
    messages: Mapping[str, list[str]]
    observations: tuple[Observation, ...]

    @classmethod
    def parse(cls, text: str) -> Journal:
        messages: dict[str, list[str]] = {}
        observations: list[Observation] = []
        for line in text.splitlines():
            if not line.strip():
                continue
            event = json.loads(line)
            message, boot = event.get("MESSAGE", ""), str(event.get("_BOOT_ID", ""))
            if not isinstance(message, str):
                continue
            messages.setdefault(boot, []).append(message)
            if message.startswith(PREFIX):
                observations.append(Observation.parse(message, boot))
        return cls(messages=messages, observations=tuple(observations))

    def lines(self, boot: str) -> list[str]:
        return self.messages.get(boot, [])

    def injections(self, boot: str, bad: str) -> list[Observation]:
        return [
            item
            for item in self.observations
            if item.boot == boot
            and item.phase == GDM_START
            and item.injected
            and item.digest == bad
        ]


def _failed_boot(journal: Journal, found: Observation, bad: str) -> str | None:
    """The counter before the health check of one failed boot of B, once its evidence holds."""
    lines = journal.lines(found.boot)
    if len(journal.injections(found.boot, bad)) != 1 or GDM_FAILED not in found.gdm_stdout:
        raise Incomplete("missing evidence of a real GDM start failure")
    if not any(INJECTED_EXIT in line for line in lines):
        raise Incomplete("GDM did not fail with the injected exit status")
    if not any(HEALTH_REJECTED in line for line in lines):
        raise Incomplete("the production Apex health check did not reject the boot")
    if (
        found.grubenv.get("boot_success") != "0"
        or found.grubenv.get("greenboot_next_deployment_id") != bad
    ):
        raise Incomplete("missing GRUB failure status or expected rollback identity")
    return found.grubenv.get("boot_counter")


def _recovered(journal: Journal, found: Observation) -> None:
    lines = journal.lines(found.boot)
    if GDM_ACTIVE not in found.gdm_stdout or not any(HEALTH_PASSED in line for line in lines):
        raise Incomplete("fallback deployment did not pass its real health check")


def _boots(journal: Journal, good: str, bad: str) -> tuple[list[str], list[str | None], str]:
    """The failed boots of B in order, their counters, and the fallback boot of A."""
    failed: list[str] = []
    counters: list[str | None] = []
    recovery: str | None = None
    for found in journal.observations:
        if found.phase != HEALTH_BEFORE:
            continue
        if found.digest == bad:
            if recovery is not None or found.boot in failed:
                raise Incomplete("repeated health check or a return to the bad deployment")
            counters.append(_failed_boot(journal, found, bad))
            failed.append(found.boot)
        elif found.digest == good and failed and recovery is None:
            _recovered(journal, found)
            recovery = found.boot
    if not failed or recovery is None:
        raise Incomplete("both fault and completed fallback boots are required")
    return failed, counters, recovery


def _judge(journal: Journal, good: str, bad: str) -> encoding.Document:
    failed, counters, recovery = _boots(journal, good, bad)
    if not any(ROLLED_BACK in line for line in journal.lines(failed[-1])):
        raise Incomplete("no successful greenboot rollback in the final failed boot")
    expected: list[str | None] = [None, *(str(n) for n in range(len(failed) - 2, -1, -1))]
    if counters != expected:
        raise Incomplete("unexpected persistent GRUB counter sequence")
    return {
        "automatic_gdm_fallback": PASS,
        "two_failure_limit": PASS if len(failed) == TWO_FAILURES else FAIL,
        "failed_boot_ids": list(failed),
        "fallback_boot_id": recovery,
        "counter_before_health": list(counters),
        "good_digest": good,
        "bad_digest": bad,
        "scope": SCOPE,
    }


def evaluate(text: str, *, good: str, bad: str) -> encoding.Document:
    """The judgement over the journal, or BLOCKED with the first piece of missing evidence."""
    try:
        return _judge(Journal.parse(text), good, bad)
    except (Incomplete, KeyError, TypeError, ValueError) as missing:
        return {"status": BLOCKED, "reason": str(missing) or type(missing).__name__}


def require_journal(collected: encoding.Document) -> str:
    programs = collected.get("programs")
    journal = programs.get("journal") if isinstance(programs, dict) else None
    if not isinstance(journal, dict) or journal.get("returncode") != 0:
        raise errors.Refusal(
            refusals.RefusalReason.UPDATE_STATE_UNEXPECTED,
            subject="the journal of the recovery units could not be read",
        )
    return str(journal.get("stdout", ""))
