"""The login and Shell stages drive the keyboard from what the guest reports, and gate later work.

The password reaches the monitor as chords and nothing else: not an observation, not a
proof, not a refusal. A seat that already holds the account refuses the run; a greeter or
a session that never comes fails it; and a stage after a failed one blocks itself without
touching the guest.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from answeringguest import Answer, AnsweringGuest
from monitorfixtures import DrawingMonitor

from apex.adapters.fakes import fake_clock, fake_files
from apex.composition import agentrun
from apex.composition import keys as composition_keys
from apex.kernel import identifiers, refusals, safepaths, secrets, verdicts
from apex.pipeline import facts, stages
from apex.ports import portset
from apex.verification import judging, probes, testaccess, verifykeys
from apex.verification.stages import login_stage, render_bars_stage, shell_startup_stage

SEED = identifiers.StageId("seed")
PASSWORD = "Ab-1_"
CREDENTIALS = testaccess.Credentials(user="apex-test", password=secrets.Secret(PASSWORD))
GREETER: Answer = {"found": True, "session": {"id": "c1", "class": "greeter"}}
ON_SEAT: Answer = {"found": True, "wayland": True, "session": {"id": "3", "type": "wayland"}}
OFF_SEAT: Answer = {"found": False, "wayland": False, "session": None}
STARTED: Answer = {"found": True, "pid": 1687, "event": {"MESSAGE": "GNOME Shell started"}}
FOLLOWED: Answer = {"reached": True}
IGNORED: Answer = {"reached": False}


@pytest.fixture
def root(tmp_path: Path) -> safepaths.RuntimeRoot:
    base = tmp_path / "runtime"
    base.mkdir(mode=0o700)
    return safepaths.RuntimeRoot.adopt(base)


def context(
    ports: portset.HostPorts,
    root: safepaths.RuntimeRoot,
    guest: AnsweringGuest,
    *,
    judged: dict[str, verdicts.Verdict] | None = None,
    credentials: testaccess.Credentials = CREDENTIALS,
) -> tuple[stages.RunContext[portset.HostPorts], DrawingMonitor]:
    assert isinstance(ports.files, fake_files.MemoryFiles)
    monitor = DrawingMonitor(ports.files)
    bundle = portset.HostPorts(
        processes=ports.processes,
        files=ports.files,
        clock=ports.clock,
        identities=ports.identities,
        locks=ports.locks,
        digests=ports.digests,
        archives=ports.archives,
        signing=ports.signing,
        downloads=ports.downloads,
        hypervisor=ports.hypervisor,
        monitor=monitor,
        guest=guest,
    )
    held = facts.FactMap()
    seeded: list[tuple[facts.FactKey[Any], object]] = [
        (verifykeys.GUEST, None),
        (
            verifykeys.AGENT,
            agentrun.AgentInstall(
                directory=safepaths.RemotePath("/var/tmp/apex-run/agent"),
                digest=identifiers.Digest("a" * 64),
            ),
        ),
        (verifykeys.MONITOR, root.child("qmp.sock")),
        (verifykeys.CREDENTIALS, credentials),
        (composition_keys.RUNTIME_ROOT, root),
        (composition_keys.RUN_ID, identifiers.RunId("b" * 32)),
    ]
    for name, verdict in (judged or {}).items():
        seeded.append((verifykeys.judged(name), judging.judge({}, verdict)))
    for key, value in seeded:
        held = held.with_fact(key, value, produced_by=SEED)
    return stages.RunContext(facts=held, ports=bundle), monitor


def login() -> stages.SimpleStage[portset.HostPorts]:
    return login_stage.for_cases(
        probes.lookup(identifiers.ProbeId("desktop.session")),
        probes.lookup(identifiers.ProbeId("desktop.greeter")),
    )


def shell() -> stages.SimpleStage[portset.HostPorts]:
    return shell_startup_stage.for_cases(
        probes.lookup(identifiers.ProbeId("desktop.shell-startup")),
        probes.lookup(identifiers.ProbeId("desktop.overview")),
        gates=(login_stage.KEY,),
    )


def slept(ports: portset.HostPorts) -> float:
    clock = ports.clock
    assert isinstance(clock, fake_clock.ManualClock)
    return round(sum(span.seconds for span in clock.slept), 3)


def test_the_password_is_typed_as_chords_at_the_greeter_and_never_filed(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    guest = AnsweringGuest({"desktop.session": [OFF_SEAT, ON_SEAT], "desktop.greeter": GREETER})
    run, monitor = context(ports, root, guest)

    result = login().apply(run)

    assert isinstance(result, stages.Advance)
    judged = result.facts[login_stage.KEY]
    assert judged.verdict is verdicts.PASSED
    assert monitor.captured() == ["greeter.png"]
    assert monitor.pressed() == [
        ["ret"],
        ["shift", "a"],
        ["b"],
        ["minus"],
        ["1"],
        ["shift", "minus"],
        ["ret"],
    ]
    assert [request["arguments"] for request in guest.requests] == [
        {"user": "apex-test", "wait": False},
        {},
        {"user": "apex-test", "wait": True},
    ]
    assert judged.observations["capture"] == "greeter.png"
    assert judged.observations["session"] == ON_SEAT
    assert PASSWORD not in json.dumps(judged.observations)
    assert all(PASSWORD.encode() not in extra.payload for extra in (judged.proof, *judged.extras))
    assert [extra.kind for extra in judged.extras] == [".json", ".json", ".png", ".json"]
    assert PASSWORD not in repr(run.facts[verifykeys.CREDENTIALS])
    assert slept(ports) == 3 + 1 + 0.1 * len(PASSWORD)


def test_an_account_already_on_the_seat_refuses_the_run_before_any_key(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    guest = AnsweringGuest({"desktop.session": ON_SEAT, "desktop.greeter": GREETER})
    run, monitor = context(ports, root, guest)

    result = login().apply(run)

    assert isinstance(result, stages.Refuse)
    assert result.reason is refusals.RefusalReason.SESSION_ALREADY_OPEN
    assert guest.asked == ["desktop.session"]
    assert monitor.executed == []


def test_a_greeter_that_never_comes_fails_the_login_without_typing(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    guest = AnsweringGuest(
        {"desktop.session": OFF_SEAT, "desktop.greeter": {"found": False, "sessions": []}}
    )
    run, monitor = context(ports, root, guest)

    result = login().apply(run)

    assert isinstance(result, stages.Advance)
    judged = result.facts[login_stage.KEY]
    assert judged.verdict is verdicts.FAILED
    assert judged.observations["capture"] is None and judged.observations["session"] is None
    assert monitor.executed == []
    assert guest.asked == ["desktop.session", "desktop.greeter"]


def test_a_session_that_never_appears_after_typing_fails_the_login(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    guest = AnsweringGuest({"desktop.session": [OFF_SEAT, OFF_SEAT], "desktop.greeter": GREETER})
    run, monitor = context(ports, root, guest)

    result = login().apply(run)

    assert isinstance(result, stages.Advance)
    assert result.facts[login_stage.KEY].verdict is verdicts.FAILED
    assert monitor.pressed()[-1] == ["ret"]
    assert guest.asked == ["desktop.session", "desktop.greeter", "desktop.session"]


def test_a_password_the_layout_cannot_type_refuses_before_the_guest_is_asked(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    guest = AnsweringGuest({"desktop.session": OFF_SEAT, "desktop.greeter": GREETER})
    untypeable = testaccess.Credentials(user="apex-test", password=secrets.Secret("pässword"))
    run, monitor = context(ports, root, guest, credentials=untypeable)

    result = login().apply(run)

    assert isinstance(result, stages.Refuse)
    assert result.reason is refusals.RefusalReason.CONSOLE_TEXT_UNSUPPORTED
    assert "ä" not in result.detail
    assert guest.asked == [] and monitor.executed == []


def test_the_shell_is_settled_welcome_dismissed_and_the_overview_round_tripped(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    guest = AnsweringGuest(
        {"desktop.shell-startup": STARTED, "desktop.overview": [FOLLOWED, FOLLOWED, FOLLOWED]}
    )
    run, monitor = context(ports, root, guest, judged={"login": verdicts.PASSED})

    result = shell().apply(run)

    assert isinstance(result, stages.Advance)
    judged = result.facts[shell_startup_stage.KEY]
    assert judged.verdict is verdicts.PASSED
    assert [command.name for command in monitor.executed] == [
        "screendump",
        "send-key",
        "send-key",
        "send-key",
        "screendump",
        "send-key",
    ]
    assert monitor.captured() == ["shell-startup.png", "overview.png"]
    assert monitor.pressed() == [["esc"], ["esc"], ["meta_l"], ["esc"]]
    assert [request["arguments"] for request in guest.requests] == [
        {},
        {"expected": False},
        {"expected": True},
        {"expected": False},
    ]
    assert judged.observations["overview_keyboard_roundtrip"] == [True, True, True]
    assert judged.observations["captures"] == ["shell-startup.png", "overview.png"]
    assert judged.observations["startup"] == STARTED
    assert [extra.kind for extra in judged.extras] == [
        ".json",
        ".png",
        ".json",
        ".json",
        ".png",
        ".json",
    ]
    assert slept(ports) == 2


def test_a_shell_that_never_reports_startup_fails_without_a_key(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    guest = AnsweringGuest({"desktop.shell-startup": {"found": False, "pid": None, "event": None}})
    run, monitor = context(ports, root, guest, judged={"login": verdicts.PASSED})

    result = shell().apply(run)

    assert isinstance(result, stages.Advance)
    judged = result.facts[shell_startup_stage.KEY]
    assert judged.verdict is verdicts.FAILED
    assert judged.observations["captures"] == []
    assert monitor.executed == [] and guest.asked == ["desktop.shell-startup"]


def test_an_overview_that_ignores_the_super_key_fails_and_stops_the_round_trip(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    guest = AnsweringGuest(
        {"desktop.shell-startup": STARTED, "desktop.overview": [FOLLOWED, IGNORED]}
    )
    run, monitor = context(ports, root, guest, judged={"login": verdicts.PASSED})

    result = shell().apply(run)

    assert isinstance(result, stages.Advance)
    judged = result.facts[shell_startup_stage.KEY]
    assert judged.verdict is verdicts.FAILED
    assert judged.observations["overview_keyboard_roundtrip"] == [True, False]
    assert judged.observations["captures"] == ["shell-startup.png"]
    assert monitor.pressed() == [["esc"], ["esc"], ["meta_l"]]
    assert guest.asked.count("desktop.overview") == 2


@pytest.mark.parametrize("earlier", [verdicts.FAILED, verdicts.BLOCKED])
def test_a_login_that_did_not_pass_blocks_the_shell_and_render_stages_untouched(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot, earlier: verdicts.Verdict
) -> None:
    guest = AnsweringGuest(
        {"desktop.shell-startup": STARTED, "desktop.render": {"presented": True}}
    )
    run, monitor = context(ports, root, guest, judged={"login": earlier, "shell.startup": earlier})
    render = render_bars_stage.for_case(
        probes.lookup(identifiers.ProbeId("desktop.render")),
        gates=(login_stage.KEY, shell_startup_stage.KEY),
    )

    blocked_shell = shell().apply(run)
    blocked_render = render.apply(run)

    outcomes = ((blocked_shell, shell_startup_stage.KEY), (blocked_render, render_bars_stage.KEY))
    for result, key in outcomes:
        assert isinstance(result, stages.Advance)
        judged = result.facts[key]
        assert judged.verdict is verdicts.BLOCKED
        assert judged.observations["blocked_by"] == "judged.login"
        assert judged.observations["earlier_verdict"] == earlier.stored_name
    assert guest.asked == [] and monitor.executed == []
