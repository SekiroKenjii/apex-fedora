"""The desktop theme recipe, run end to end on fakes.

The guest answers each unit request from a table and the monitor writes the frames a test
declares wherever the host names them. Every window is shown, captured and dismissed, the
Shell surface is judged, the settings are judged, and then the chain refuses the fake
bundle: a simulated run is never recorded.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from answeringguest import Answer, AnsweringGuest

from apex.adapters.fakes import fake_clock, fake_files, fake_qmp
from apex.attestation import ledger, proofs
from apex.composition import keys as composition_keys
from apex.config import defaults
from apex.kernel import claims, identifiers, refusals, safepaths, secrets, verdicts
from apex.ports import guestshell, portset, qmp
from apex.verification import recording, verifykeys
from apex.verification.recipes import desktop_theme_recipe
from apex.verification.stages import shell_surface_stage, theme_settings_stage

CANDIDATE = identifiers.Digest("c" * 64)
HEADER = b"P6\n300 100\n255\n"
BLACK = HEADER + b"\x00\x00\x00" * 300 * 100
GREY = HEADER + b"\x40\x40\x40" * 300 * 100
FRAMES = {"shell-before.ppm": BLACK, "shell-surface.ppm": GREY}


def presented(mode: str) -> Answer:
    return {
        "mode": mode, "unit": f"apex-theme-{mode}", "presented": True,
        "display_type": "GdkWaylandDisplay", "visual_review": "NOT TESTED",
    }


def settings(gtk: str = "'Adwaita-dark'", shell: str = "'Shadcn-Graphite'") -> Answer:
    return {
        "settings": {
            "gtk_theme": {"returncode": 0, "stdout": f"{gtk}\n"},
            "shell_theme": {"returncode": 0, "stdout": f"{shell}\n"},
            "extensions": {"returncode": 0, "stdout": "user-theme\n"},
        },
        "composition": {"text": "{}"},
    }


def answers(**changes: Answer | list[Answer]) -> dict[str, Answer | list[Answer]]:
    table: dict[str, Answer | list[Answer]] = {
        "desktop.theme-gtk3": [presented("gtk3"), {"stop": {"returncode": 0}}],
        "desktop.theme-adwaita": [presented("adwaita"), {"stop": {"returncode": 0}}],
        "desktop.theme-settings": settings(),
    }
    table.update(changes)
    return table


class DrawingMonitor(fake_qmp.ScriptedQmp):
    """Writes the declared frame to the file each screendump names, through the host's files."""

    def __init__(self, files: fake_files.MemoryFiles, frames: dict[str, bytes]) -> None:
        super().__init__({"screendump": {}, "send-key": {}})
        self.frames = frames
        self.react_to("screendump", lambda command: self._draw(files, command))

    def _draw(self, files: fake_files.MemoryFiles, command: qmp.QmpCommand) -> None:
        path = Path(str(command.arguments["filename"]))
        payload = self.frames.get(path.name, b"png bytes")
        files.write_atomic(
            safepaths.SafePath(path), payload, mode=defaults.RECORD_MODE
        )


@pytest.fixture
def root(tmp_path: Path) -> safepaths.RuntimeRoot:
    base = tmp_path / "runtime"
    base.mkdir(mode=0o700)
    (base / "guest_ed25519").write_bytes(b"")
    (base / "apex-agent.whl").write_bytes(b"not a wheel")
    return safepaths.RuntimeRoot.adopt(base)


def guest_target(root: safepaths.RuntimeRoot) -> guestshell.GuestTarget:
    return guestshell.GuestTarget(
        user="tester",
        port=defaults.GUEST_SSH_PORT,
        key=safepaths.SafePath.regular_file(root.path / "guest_ed25519", within=root),
        known_hosts=root.child(defaults.KNOWN_HOSTS_NAME),
    )


def recorder(root: safepaths.RuntimeRoot) -> recording.Recorder:
    location = proofs.StoreLocation(root=root)
    filesystem = fake_files.MemoryFiles()
    return recording.Recorder(
        store=proofs.ProofStore(location=location, filesystem=filesystem),
        chain=ledger.Ledger(
            location=location, filesystem=filesystem,
            signer=ledger.ChainSigner(secrets.Secret("key")), clock=fake_clock.ManualClock(),
        ),
    )


def verify(
    ports: portset.HostPorts,
    root: safepaths.RuntimeRoot,
    guest: AnsweringGuest,
    frames: dict[str, bytes] | None = None,
) -> tuple[object, recording.Recorder, DrawingMonitor]:
    assert isinstance(ports.files, fake_files.MemoryFiles)
    monitor = DrawingMonitor(ports.files, dict(FRAMES if frames is None else frames))
    bundle = portset.HostPorts(
        processes=ports.processes, files=ports.files, clock=ports.clock,
        identities=ports.identities, locks=ports.locks, digests=ports.digests,
        archives=ports.archives, signing=ports.signing, downloads=ports.downloads,
        hypervisor=ports.hypervisor, monitor=monitor, guest=guest,
    )
    held = recorder(root)
    outcome = desktop_theme_recipe.verify(
        bundle,
        guest=guest_target(root),
        wheel=safepaths.SafePath.regular_file(root.path / "apex-agent.whl", within=root),
        candidate=CANDIDATE,
        witness=claims.EnvironmentKind.VM,
        recorder=held,
        monitor=root.child("qmp.sock"),
        root=root,
    )
    return outcome, held, monitor


def test_the_plan_shows_each_window_then_the_shell_then_the_settings_then_records() -> None:
    assert [str(item) for item in desktop_theme_recipe.PLAN.order] == [
        "run.identify",
        "agent.deliver",
        "desktop.window-gtk3",
        "desktop.window-adwaita",
        "desktop.shell-surface",
        "desktop.theme-settings",
        "attest.desktop.theme-surfaces",
    ]


def test_every_surface_is_judged_and_the_fake_bundle_is_refused_before_the_chain(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    guest = AnsweringGuest(answers())

    outcome, held, monitor = verify(ports, root, guest)

    assert outcome.refusal is refusals.RefusalReason.SIMULATED_ENVIRONMENT  # type: ignore[attr-defined]
    assert outcome.not_tested == (desktop_theme_recipe.CHECK,)  # type: ignore[attr-defined]
    assert guest.asked == [
        "desktop.theme-gtk3", "desktop.theme-gtk3",
        "desktop.theme-adwaita", "desktop.theme-adwaita",
        "desktop.theme-settings",
    ]
    assert [request["arguments"] for request in guest.requests] == [
        {"action": "present"}, {"action": "dismiss"},
        {"action": "present"}, {"action": "dismiss"},
        {},
    ]
    assert all("sudo" not in run.script.rendered() for run in guest.runs)
    facts = outcome.facts  # type: ignore[attr-defined]
    for name in ("window.gtk3", "window.adwaita", "shell.surface", "theme.settings"):
        assert facts[verifykeys.judged(name)].verdict is verdicts.PASSED, name
    assert [command.name for command in monitor.executed] == [
        "send-key", "screendump",
        "send-key", "screendump",
        "screendump", "send-key", "screendump", "screendump", "send-key",
    ]
    run = facts[composition_keys.RUN_ID]
    names = [
        Path(str(command.arguments["filename"])).name
        for command in monitor.executed
        if command.name == "screendump"
    ]
    assert names == [
        "gtk3.png", "adwaita.png", "shell-before.ppm", "shell-surface.ppm", "shell-surface.png",
    ]
    assert all(
        str(command.arguments["filename"]).startswith(f"{root.path}/exports/{run}/screens/")
        for command in monitor.executed
        if command.name == "screendump"
    )
    shell = facts[shell_surface_stage.KEY]
    assert shell.observations["changed_pixels"] == 300 * 60
    assert [extra.kind for extra in shell.extras] == [".png"]
    window = facts[verifykeys.judged("window.gtk3")]
    assert [extra.kind for extra in window.extras] == [".json", ".png"]
    assert held.chain.head() == ledger.EMPTY
    assert held.store.absorbed == 0


def test_a_window_that_never_presents_blocks_and_is_not_captured_or_dismissed(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    silent: list[Answer] = [{"presented": False}]
    guest = AnsweringGuest(answers(**{"desktop.theme-gtk3": silent}))

    outcome, _, monitor = verify(ports, root, guest)

    facts = outcome.facts  # type: ignore[attr-defined]
    window = facts[verifykeys.judged("window.gtk3")]
    assert window.verdict is verdicts.BLOCKED
    assert window.observations["capture"] is None
    assert guest.asked.count("desktop.theme-gtk3") == 1
    names = [
        Path(str(command.arguments["filename"])).name
        for command in monitor.executed
        if command.name == "screendump"
    ]
    assert "gtk3.png" not in names and "adwaita.png" in names


def test_an_unchanged_shell_fails_the_surface_and_other_themes_fail_the_settings(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    guest = AnsweringGuest(answers(**{"desktop.theme-settings": settings(gtk="'Adwaita'")}))

    outcome, _, _ = verify(ports, root, guest, frames={**FRAMES, "shell-surface.ppm": BLACK})

    facts = outcome.facts  # type: ignore[attr-defined]
    assert facts[shell_surface_stage.KEY].verdict is verdicts.FAILED
    settled = facts[theme_settings_stage.KEY]
    assert settled.verdict is verdicts.FAILED
    assert settled.observations["reported"] == {
        "gtk_theme": "'Adwaita'", "shell_theme": "'Shadcn-Graphite'"
    }


def test_frames_of_two_sizes_refuse_the_run_as_a_broken_capture(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    guest = AnsweringGuest(answers())
    small = b"P6\n1 1\n255\n\x00\x00\x00"

    outcome, _, _ = verify(ports, root, guest, frames={**FRAMES, "shell-surface.ppm": small})

    assert outcome.refusal is refusals.RefusalReason.SCREEN_SIZE_CHANGED  # type: ignore[attr-defined]
    assert "desktop.shell-surface" in outcome.detail  # type: ignore[attr-defined]
