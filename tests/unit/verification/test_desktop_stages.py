"""The render bars stage retries as the older host did and judges bars, display and presence."""

from __future__ import annotations

from pathlib import Path

import pytest
from answeringguest import AnsweringGuest

from apex.adapters.fakes import fake_clock, fake_files, fake_qmp
from apex.composition import agentrun
from apex.composition import keys as composition_keys
from apex.config import defaults
from apex.kernel import identifiers, refusals, safepaths, verdicts
from apex.pipeline import facts, stages
from apex.ports import portset, qmp
from apex.verification import probes, verifykeys
from apex.verification.stages import render_bars_stage, theme_settings_stage

SEED = identifiers.StageId("seed")
HEADER = b"P6\n300 100\n255\n"
BARS = HEADER + (b"\xe6\x26\x26" * 100 + b"\x26\xbf\x40" * 100 + b"\x26\x4c\xe6" * 100) * 100
BLANK = HEADER + b"\x00\x00\x00" * 300 * 100


class FramesInOrder(fake_qmp.ScriptedQmp):
    """Answers each screendump with the next declared frame, the last one repeating."""

    def __init__(self, files: fake_files.MemoryFiles, frames: list[bytes]) -> None:
        super().__init__({"screendump": {}, "send-key": {}})
        self.frames = list(frames)
        self.react_to("screendump", lambda command: self._draw(files, command))

    def _draw(self, files: fake_files.MemoryFiles, command: qmp.QmpCommand) -> None:
        payload = self.frames.pop(0) if len(self.frames) > 1 else self.frames[0]
        files.write_atomic(
            safepaths.SafePath(Path(str(command.arguments["filename"]))),
            payload,
            mode=defaults.RECORD_MODE,
        )


@pytest.fixture
def root(tmp_path: Path) -> safepaths.RuntimeRoot:
    base = tmp_path / "runtime"
    base.mkdir(mode=0o700)
    (base / "guest_ed25519").write_bytes(b"")
    return safepaths.RuntimeRoot.adopt(base)


def context(
    ports: portset.HostPorts,
    root: safepaths.RuntimeRoot,
    guest: AnsweringGuest,
    frames: list[bytes],
) -> tuple[stages.RunContext[portset.HostPorts], FramesInOrder]:
    assert isinstance(ports.files, fake_files.MemoryFiles)
    monitor = FramesInOrder(ports.files, frames)
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
    for key, value in (
        (verifykeys.GUEST, None),
        (
            verifykeys.AGENT,
            agentrun.AgentInstall(
                directory=safepaths.RemotePath("/var/tmp/apex-run/agent"),
                digest=identifiers.Digest("a" * 64),
            ),
        ),
        (verifykeys.MONITOR, root.child("qmp.sock")),
        (composition_keys.RUNTIME_ROOT, root),
        (composition_keys.RUN_ID, identifiers.RunId("b" * 32)),
    ):
        held = held.with_fact(key, value, produced_by=SEED)
    return stages.RunContext(facts=held, ports=bundle), monitor


def render_case() -> object:
    return probes.lookup(identifiers.ProbeId("desktop.render"))


def test_bars_that_appear_on_the_third_frame_pass_after_three_tries(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    guest = AnsweringGuest(
        {"desktop.render": {"presented": True, "display_type": "GdkWaylandDisplay"}}
    )
    run, monitor = context(ports, root, guest, [BLANK, BLANK, BARS])
    stage = render_bars_stage.for_case(render_case())  # type: ignore[arg-type]

    result = stage.apply(run)

    assert isinstance(result, stages.Advance)
    judged = result.facts[render_bars_stage.KEY]
    assert judged.verdict is verdicts.PASSED
    assert judged.observations["bars"]["visible"] is True  # type: ignore[index]
    assert [command.name for command in monitor.executed] == [
        "send-key",
        "screendump",
        "send-key",
        "screendump",
        "send-key",
        "screendump",
        "screendump",
    ]
    assert [extra.kind for extra in judged.extras] == [".json", ".png"]
    clock = ports.clock
    assert isinstance(clock, fake_clock.ManualClock)
    assert sum(span.seconds for span in clock.slept) == 5


def test_bars_that_never_appear_fail_after_the_older_deadline(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    guest = AnsweringGuest(
        {"desktop.render": {"presented": True, "display_type": "GdkWaylandDisplay"}}
    )
    run, monitor = context(ports, root, guest, [BLANK])
    stage = render_bars_stage.for_case(render_case())  # type: ignore[arg-type]

    result = stage.apply(run)

    assert isinstance(result, stages.Advance)
    judged = result.facts[render_bars_stage.KEY]
    assert judged.verdict is verdicts.FAILED
    assert judged.observations["bars"]["visible"] is False  # type: ignore[index]
    clock = ports.clock
    assert isinstance(clock, fake_clock.ManualClock)
    assert sum(span.seconds for span in clock.slept) >= 45
    assert monitor.executed[-1].name == "screendump"


def test_a_display_that_is_not_wayland_fails_even_with_bars(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    guest = AnsweringGuest({"desktop.render": {"presented": True, "display_type": "GdkX11Display"}})
    run, _ = context(ports, root, guest, [BARS])

    result = render_bars_stage.for_case(render_case()).apply(run)  # type: ignore[arg-type]

    assert isinstance(result, stages.Advance)
    assert result.facts[render_bars_stage.KEY].verdict is verdicts.FAILED


def test_a_window_that_never_presents_blocks_without_a_capture(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    guest = AnsweringGuest({"desktop.render": {"presented": False, "display_type": None}})
    run, monitor = context(ports, root, guest, [BARS])

    result = render_bars_stage.for_case(render_case()).apply(run)  # type: ignore[arg-type]

    assert isinstance(result, stages.Advance)
    judged = result.facts[render_bars_stage.KEY]
    assert judged.verdict is verdicts.BLOCKED
    assert judged.observations["capture"] is None
    assert monitor.executed == []


def test_a_guest_that_refuses_the_probe_refuses_the_stage(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    run, _ = context(ports, root, AnsweringGuest({}), [BARS])

    result = render_bars_stage.for_case(render_case()).apply(run)  # type: ignore[arg-type]

    assert isinstance(result, stages.Refuse)
    assert result.reason is refusals.RefusalReason.AGENT_REFUSED


@pytest.mark.parametrize(
    "observations,expected",
    [
        ({}, verdicts.BLOCKED),
        ({"settings": {"gtk_theme": {"returncode": 1, "stdout": ""}}}, verdicts.BLOCKED),
        (
            {
                "settings": {
                    "gtk_theme": {"returncode": 0, "stdout": "'Adwaita-dark'\n"},
                    "shell_theme": {"returncode": 0, "stdout": "'Other'\n"},
                }
            },
            verdicts.FAILED,
        ),
        (
            {
                "settings": {
                    "gtk_theme": {"returncode": 0, "stdout": "'Adwaita-dark'\n"},
                    "shell_theme": {"returncode": 0, "stdout": "'Shadcn-Graphite'\n"},
                }
            },
            verdicts.PASSED,
        ),
    ],
)
def test_the_settings_verdict_blocks_on_silence_and_fails_on_another_theme(
    observations: dict[str, object], expected: verdicts.Verdict
) -> None:
    verdict, _ = theme_settings_stage.verdict_of(observations)  # type: ignore[arg-type]

    assert verdict is expected
