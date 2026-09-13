"""Run the rebuilt library's packaged C tests over fake devices in the builder.

The two packages come from the host's copy of a completed package build, digested before
they are sent; the guest installs them offline and runs the two test programs as its
unprivileged account; the report must name exactly those packages, both programs passed,
and no hardware claim.
"""

from __future__ import annotations

from apex.composition import exports, fingerprintpackages
from apex.composition import keys as composition_keys
from apex.composition.stages import identify_run_stage
from apex.config import defaults
from apex.kernel import encoding, identifiers, safepaths
from apex.pipeline import plans, runner, stages
from apex.ports import guestshell, portset
from apex.verification import verifykeys
from apex.verification.stages import builder_guard_stage, builder_test_stage

NAME = "verify-fingerprint-rpms"
UNIT = "fingerprint.rpm-smoke"
WORK_PREFIX = "/var/tmp/apex-fingerprint-rpm-tests-"


def prepare(context: stages.RunContext[portset.HostPorts]) -> builder_test_stage.BuilderTest:
    ports = context.ports
    root = context.facts[composition_keys.RUNTIME_ROOT]
    run = context.facts[composition_keys.RUN_ID]
    repository = context.facts[composition_keys.REPOSITORY]
    lock = fingerprintpackages.load_lock(repository)
    packages = exports.inside(
        root, context.facts[verifykeys.PARENT],
        f"{exports.OUTPUT}/{fingerprintpackages.LIBRARY}/"
        f"{defaults.FINGERPRINT_MOCK_DIRECTORY}",
    )
    inputs = {
        name: ports.digests.file(
            safepaths.SafePath.regular_file(packages.path / name, within=root)
        ).hex
        for name in fingerprintpackages.smoke_rpms(lock)
    }
    listing = exports.inside(root, run, defaults.SMOKE_INPUTS_NAME)
    ports.files.write_atomic(listing, encoding.canonical(inputs) + b"\n", mode=defaults.RECORD_MODE)
    remote = safepaths.RemotePath(f"{WORK_PREFIX}{run}")
    inputs_directory = remote.joined(defaults.FINGERPRINT_INPUTS_DIRECTORY)
    return builder_test_stage.BuilderTest(
        remote=remote,
        deliveries=(
            *((packages / name, inputs_directory.joined(name)) for name in inputs),
            (listing, remote.joined(defaults.SMOKE_INPUTS_NAME)),
            (
                safepaths.SafePath(repository.path / defaults.SMOKE_SCRIPT_PATH),
                remote.joined(defaults.SMOKE_SCRIPT_NAME),
            ),
        ),
        script=guestshell.RemoteScript.of(
            guestshell.Step.of("cd", str(remote)),
            guestshell.Step.of(
                "sudo", "flock", "-n", str(defaults.FINGERPRINT_TEST_LOCK), "python3",
                defaults.SMOKE_SCRIPT_NAME,
            ),
        ),
        transcript=defaults.SMOKE_LOG_NAME,
        inputs=inputs,
    )


def judge(
    _ports: portset.HostPorts,
    _root: safepaths.RuntimeRoot,
    _home: safepaths.SafePath,
    test: builder_test_stage.BuilderTest,
    document: encoding.Document,
) -> str | None:
    return fingerprintpackages.judge_smoke(document, test.inputs)


STAGES = (
    identify_run_stage.STAGE,
    builder_guard_stage.STAGE,
    builder_test_stage.for_test(UNIT, prepare=prepare, judge=judge),
)
SEEDS = frozenset({
    verifykeys.BUILDER, verifykeys.PARENT, composition_keys.RUNTIME_ROOT,
    composition_keys.REPOSITORY,
})
PLAN: plans.Plan[portset.HostPorts] = plans.Plan.of(NAME, STAGES, seeds=SEEDS)


def verify(
    ports: portset.HostPorts,
    *,
    builder: guestshell.GuestTarget,
    parent: identifiers.BuildId,
    root: safepaths.RuntimeRoot,
    repository: safepaths.SourceRoot,
) -> runner.Outcome:
    return runner.run(
        PLAN,
        ports=ports,
        seeds={
            verifykeys.BUILDER: builder,
            verifykeys.PARENT: parent,
            composition_keys.RUNTIME_ROOT: root,
            composition_keys.REPOSITORY: repository,
        },
    )
