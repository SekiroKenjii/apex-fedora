"""Capture the session's theme surfaces and record one result for them.

Two theme windows, one Shell surface and the session's settings, one check: each window must
present, the Shell must visibly open its surface, and the settings must name the themes the
image ships for `desktop.theme-surfaces` to pass. The captures are filed for the reviewer;
the visual review itself stays NOT TESTED in every record this recipe makes.
"""

from __future__ import annotations

from apex.composition import keys as composition_keys
from apex.composition.stages import identify_run_stage
from apex.kernel import claims, identifiers, safepaths
from apex.pipeline import plans, runner
from apex.ports import guestshell, portset
from apex.verification import probes, recording, verifykeys
from apex.verification.stages import (
    deliver_agent_stage,
    mint_stage,
    shell_surface_stage,
    theme_settings_stage,
    theme_window_stage,
)

NAME = "verify-desktop-theme"
CHECK = identifiers.CheckId("desktop.theme-surfaces")
MODES = ("gtk3", "adwaita")
WINDOW_KEYS = tuple(verifykeys.judged(f"window.{mode}") for mode in MODES)
WINDOWS = tuple(
    theme_window_stage.for_mode(
        probes.lookup(identifiers.ProbeId(f"desktop.theme-{mode}")), mode, after=WINDOW_KEYS[:index]
    )
    for index, mode in enumerate(MODES)
)
SETTINGS = theme_settings_stage.for_case(
    probes.lookup(identifiers.ProbeId("desktop.theme-settings")), after=(shell_surface_stage.KEY,)
)
STAGES = (
    identify_run_stage.STAGE,
    deliver_agent_stage.STAGE,
    *WINDOWS,
    shell_surface_stage.after(*WINDOW_KEYS),
    SETTINGS,
    mint_stage.for_check(
        CHECK, reports=[*WINDOW_KEYS, shell_surface_stage.KEY, theme_settings_stage.KEY]
    ),
)
SEEDS = frozenset({
    verifykeys.GUEST,
    verifykeys.WHEEL,
    verifykeys.CANDIDATE,
    verifykeys.WITNESS,
    verifykeys.RECORDER,
    verifykeys.MONITOR,
    composition_keys.RUNTIME_ROOT,
})
PLAN: plans.Plan[portset.HostPorts] = plans.Plan.of(NAME, STAGES, seeds=SEEDS)


def verify(
    ports: portset.HostPorts,
    *,
    guest: guestshell.GuestTarget,
    wheel: safepaths.SafePath,
    candidate: identifiers.Digest,
    witness: claims.EnvironmentKind,
    recorder: recording.Recorder,
    monitor: safepaths.SafePath,
    root: safepaths.RuntimeRoot,
) -> runner.Outcome:
    return runner.run(
        PLAN,
        ports=ports,
        seeds={
            verifykeys.GUEST: guest,
            verifykeys.WHEEL: wheel,
            verifykeys.CANDIDATE: candidate,
            verifykeys.WITNESS: witness,
            verifykeys.RECORDER: recorder,
            verifykeys.MONITOR: monitor,
            composition_keys.RUNTIME_ROOT: root,
        },
    )
