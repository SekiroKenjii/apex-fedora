"""Log in at GDM by keyboard, settle the Shell, show the render probe, record one result.

Three judgements, one check: the password must be accepted into a Wayland session on the
seat, the Shell must report its startup and follow the Overview keys, and the GTK4 probe's
bars must be visible in the hypervisor's frame for `desktop.password-wayland` to pass. Each
stage after the login blocks itself when an earlier judgement did not pass, so the record
carries the first failure and the guest is not asked to do what it cannot.
"""

from __future__ import annotations

from apex.composition import keys as composition_keys
from apex.composition.stages import identify_run_stage
from apex.kernel import claims, identifiers, safepaths
from apex.pipeline import plans, runner
from apex.ports import guestshell, portset
from apex.verification import probes, recording, testaccess, verifykeys
from apex.verification.stages import (
    deliver_agent_stage,
    login_stage,
    mint_stage,
    render_bars_stage,
    shell_startup_stage,
)

NAME = "verify-desktop-render"
CHECK = identifiers.CheckId("desktop.password-wayland")
LOGIN = login_stage.for_cases(
    probes.lookup(identifiers.ProbeId("desktop.session")),
    probes.lookup(identifiers.ProbeId("desktop.greeter")),
)
SHELL = shell_startup_stage.for_cases(
    probes.lookup(identifiers.ProbeId("desktop.shell-startup")),
    probes.lookup(identifiers.ProbeId("desktop.overview")),
    gates=(login_stage.KEY,),
)
RENDER = render_bars_stage.for_case(
    probes.lookup(identifiers.ProbeId("desktop.render")),
    gates=(login_stage.KEY, shell_startup_stage.KEY),
)
STAGES = (
    identify_run_stage.STAGE,
    deliver_agent_stage.STAGE,
    LOGIN,
    SHELL,
    RENDER,
    mint_stage.for_check(
        CHECK, reports=[login_stage.KEY, shell_startup_stage.KEY, render_bars_stage.KEY]
    ),
)
SEEDS = frozenset({
    verifykeys.GUEST,
    verifykeys.WHEEL,
    verifykeys.CANDIDATE,
    verifykeys.WITNESS,
    verifykeys.RECORDER,
    verifykeys.MONITOR,
    verifykeys.CREDENTIALS,
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
    credentials: testaccess.Credentials,
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
            verifykeys.CREDENTIALS: credentials,
            composition_keys.RUNTIME_ROOT: root,
        },
    )
