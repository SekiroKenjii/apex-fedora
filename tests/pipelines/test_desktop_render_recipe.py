"""The desktop render recipe, run end to end on fakes.

The guest answers each unit request from a table and the monitor draws the frames a test
declares wherever the host names them. The account is logged in by keyboard, the Shell is
settled, the bars are judged, and then the chain refuses the fake bundle: a simulated run
is never recorded. A login that fails blocks everything after it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from answeringguest import Answer, AnsweringGuest
from monitorfixtures import DrawingMonitor
from test_desktop_theme_recipe import CANDIDATE, guest_target, recorder

from apex.adapters.fakes import fake_files
from apex.attestation import ledger
from apex.kernel import claims, refusals, safepaths, secrets, verdicts
from apex.ports import portset
from apex.verification import desktopplans, testaccess, verifykeys
from apex.verification.recipes import desktop_render_recipe
from apex.verification.stages import login_stage, render_bars_stage, shell_startup_stage

HEADER = b"P6\n300 100\n255\n"
BARS = HEADER + (b"\xe6\x26\x26" * 100 + b"\x26\xbf\x40" * 100 + b"\x26\x4c\xe6" * 100) * 100
PASSWORD = "Ab-1_"
CREDENTIALS = testaccess.Credentials(user="tester", password=secrets.Secret(PASSWORD))


@pytest.fixture
def root(tmp_path: Path) -> safepaths.RuntimeRoot:
    base = tmp_path / "runtime"
    base.mkdir(mode=0o700)
    (base / "guest_ed25519").write_bytes(b"")
    (base / "apex-agent.whl").write_bytes(b"not a wheel")
    return safepaths.RuntimeRoot.adopt(base)


def answers(**changes: Answer | list[Answer]) -> dict[str, Answer | list[Answer]]:
    table: dict[str, Answer | list[Answer]] = {
        "desktop.session": [
            {"found": False, "wayland": False},
            {"found": True, "wayland": True, "session": {"id": "3", "type": "wayland"}},
        ],
        "desktop.greeter": {"found": True, "session": {"id": "c1", "class": "greeter"}},
        "desktop.shell-startup": {"found": True, "pid": 1687, "event": {"MESSAGE": "started"}},
        "desktop.overview": [{"reached": True}, {"reached": True}, {"reached": True}],
        "desktop.render": {"presented": True, "display_type": "GdkWaylandDisplay"},
    }
    table.update(changes)
    return table


def verify(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot, guest: AnsweringGuest
) -> tuple[object, DrawingMonitor]:
    assert isinstance(ports.files, fake_files.MemoryFiles)
    monitor = DrawingMonitor(ports.files, {"application.ppm": BARS})
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
    held = recorder(root)
    outcome = desktop_render_recipe.verify(
        bundle,
        desktopplans.Inputs(
            guest=guest_target(root),
            wheel=safepaths.SafePath.regular_file(root.path / "apex-agent.whl", within=root),
            candidate=CANDIDATE,
            witness=claims.EnvironmentKind.VM,
            recorder=held,
            monitor=root.child("qmp.sock"),
            root=root,
            credentials=CREDENTIALS,
        ),
    )
    assert held.chain.head() == ledger.EMPTY
    return outcome, monitor


def test_the_plan_logs_in_then_settles_the_shell_then_judges_the_bars_then_records() -> None:
    assert [str(item) for item in desktop_render_recipe.PLAN.order] == [
        "run.identify",
        "agent.deliver",
        "desktop.login",
        "desktop.shell-startup",
        "desktop.render-bars",
        "attest.desktop.password-wayland",
    ]


def test_the_account_is_logged_in_by_keyboard_and_every_stage_passes_before_the_chain_refuses(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    guest = AnsweringGuest(answers())

    outcome, monitor = verify(ports, root, guest)

    assert outcome.refusal is refusals.RefusalReason.SIMULATED_ENVIRONMENT  # type: ignore[attr-defined]
    assert outcome.not_tested == (desktop_render_recipe.CHECK,)  # type: ignore[attr-defined]
    assert guest.asked == [
        "desktop.session",
        "desktop.greeter",
        "desktop.session",
        "desktop.shell-startup",
        "desktop.overview",
        "desktop.overview",
        "desktop.overview",
        "desktop.render",
    ]
    assert all("sudo" not in run.script.rendered() for run in guest.runs)
    facts = outcome.facts  # type: ignore[attr-defined]
    for key in (login_stage.KEY, shell_startup_stage.KEY, render_bars_stage.KEY):
        assert facts[key].verdict is verdicts.PASSED, key
    assert monitor.captured() == [
        "greeter.png",
        "shell-startup.png",
        "overview.png",
        "application.ppm",
        "application.png",
    ]
    assert monitor.pressed()[:8] == [
        ["ret"],
        ["shift", "a"],
        ["b"],
        ["minus"],
        ["1"],
        ["shift", "minus"],
        ["ret"],
        ["esc"],
    ]
    keys = (login_stage.KEY, shell_startup_stage.KEY, render_bars_stage.KEY)
    filed = [facts[key] for key in keys]
    assert all(PASSWORD not in json.dumps(item.observations) for item in filed)
    assert all(
        PASSWORD.encode() not in extra.payload
        for item in filed
        for extra in (item.proof, *item.extras)
    )


def test_a_login_that_fails_blocks_the_shell_and_the_bars_without_asking_the_guest(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    guest = AnsweringGuest(answers(**{"desktop.greeter": {"found": False, "sessions": []}}))

    outcome, monitor = verify(ports, root, guest)

    facts = outcome.facts  # type: ignore[attr-defined]
    assert facts[login_stage.KEY].verdict is verdicts.FAILED
    assert facts[shell_startup_stage.KEY].verdict is verdicts.BLOCKED
    assert facts[render_bars_stage.KEY].verdict is verdicts.BLOCKED
    assert facts[render_bars_stage.KEY].observations["blocked_by"] == "judged.login"
    assert guest.asked == ["desktop.session", "desktop.greeter"]
    assert monitor.executed == []


@pytest.mark.parametrize("key", [verifykeys.CREDENTIALS, verifykeys.MONITOR])
def test_the_plan_is_seeded_with_the_credentials_and_the_monitor(key: object) -> None:
    assert key in desktop_render_recipe.SEEDS
