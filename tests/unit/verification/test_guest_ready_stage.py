"""The guest is waited for over ssh until systemd reports the system running."""

from __future__ import annotations

import dataclasses
from pathlib import Path

from apex.adapters.fakes import fake_clock, fake_guestshell
from apex.config import defaults
from apex.kernel import errors, identifiers, refusals, safepaths
from apex.pipeline import facts, stages
from apex.ports import guestshell, portset
from apex.verification import verifykeys
from apex.verification.stages import guest_ready_stage

SCRIPT = "systemd-detect-virt --vm && systemctl is-system-running || true"


def target() -> guestshell.GuestTarget:
    return guestshell.GuestTarget(
        user="apex-test",
        port=defaults.GUEST_SSH_PORT,
        key=safepaths.SafePath(Path("/runtime/id_ed25519")),
        known_hosts=safepaths.SafePath(Path("/runtime/known_hosts")),
    )


class Booting(fake_guestshell.ScriptedGuest):
    """Unreachable for a few attempts, then degraded, then running."""

    def __init__(self, answers: list[bytes | None]) -> None:
        super().__init__(strict=True)
        self.answers = answers

    def run(self, target: guestshell.GuestTarget, run: guestshell.GuestRun) -> object:  # type: ignore[override]
        answer = self.answers.pop(0)
        if answer is None:
            raise errors.PortFailure(port="guest", cause="connection refused")
        self.expect(run.script.rendered(), fake_guestshell.GuestReply(stdout=answer))
        return super().run(target, run)


def context(ports: portset.HostPorts, guest: Booting) -> stages.RunContext[portset.HostPorts]:
    held = dataclasses.replace(ports, guest=guest, clock=fake_clock.ManualClock())
    seeded = facts.FactMap().with_fact(
        verifykeys.GUEST, target(), produced_by=identifiers.StageId("seed")
    )
    return stages.RunContext(ports=held, facts=seeded)


def test_the_stage_waits_through_refused_connections_and_a_degraded_system(
    ports: portset.HostPorts,
) -> None:
    guest = Booting([None, None, b"kvm\nstarting\n", b"kvm\ndegraded\n"])

    result = guest_ready_stage.STAGE.apply(context(ports, guest))

    assert isinstance(result, stages.Advance)
    found = result.facts[verifykeys.READY]
    assert found == {"virtualiser": "kvm", "system": "degraded", "waited_seconds": 6, "attempts": 4}
    assert guest.runs[-1].script.rendered() == SCRIPT


def test_a_guest_that_never_answers_is_a_refusal_with_the_last_answer(
    ports: portset.HostPorts,
) -> None:
    guest = Booting([b"none\nrunning\n"] * 200)

    result = guest_ready_stage.STAGE.apply(context(ports, guest))

    assert isinstance(result, stages.Refuse)
    assert result.reason is refusals.RefusalReason.GUEST_NOT_READY
    assert "['none', 'running']" in result.detail
