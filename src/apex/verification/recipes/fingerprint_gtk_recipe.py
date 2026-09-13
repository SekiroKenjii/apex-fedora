"""Compile and drive the whole GNOME fingerprint dialog in the builder, original and patched.

The runner, its harness and its mock service come from the checkout, the settings archive
from the host's copy of the package build, and the patch the checkout carries must be the
one that build applied; every input is digested into a request the guest verifies before
it starts. The report must name those inputs, and every case's log must digest to what the
report says before the run is kept as a pass.
"""

from __future__ import annotations

from apex.composition import exports, fingerprintpackages
from apex.composition import keys as composition_keys
from apex.composition.stages import identify_run_stage
from apex.config import defaults
from apex.kernel import encoding, errors, identifiers, refusals, safepaths
from apex.pipeline import plans, runner, stages
from apex.ports import guestshell, portset
from apex.verification import verifykeys
from apex.verification.stages import builder_guard_stage, builder_test_stage

NAME = "verify-fingerprint-gtk"
UNIT = "fingerprint.gtk"
WORK_PREFIX = "/var/tmp/apex-fingerprint-gtk-"
RUNNER = "guest/fingerprint-gtk.py"


def _archive(
    root: safepaths.RuntimeRoot, parent: identifiers.BuildId,
    lock: fingerprintpackages.PackageLock,
) -> tuple[str, safepaths.SafePath]:
    settings = lock.package(fingerprintpackages.SETTINGS)
    archive = exports.inside(
        root, parent, f"{exports.OUTPUT}/{settings.name}/sources/{settings.archive}"
    )
    return settings.archive, safepaths.SafePath.regular_file(archive.path, within=root)


def _require_built_patch(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot, parent: identifiers.BuildId,
    lock: fingerprintpackages.PackageLock, patches: dict[str, identifiers.Digest],
) -> None:
    report = fingerprintpackages.parse_rpm_report(
        encoding.parse_object(ports.files.read_bytes(
            exports.inside(root, parent, f"{exports.OUTPUT}/{defaults.RESULTS_NAME}"),
            limit=defaults.DOCUMENT_LIMIT.value,
        )),
        lock, patches,
    )
    if report.patches[fingerprintpackages.SETTINGS] != patches[fingerprintpackages.SETTINGS].hex:
        raise errors.Refusal(
            refusals.RefusalReason.FINGERPRINT_INPUT_MISMATCH,
            subject="the checkout's patch differs from the built package's",
        )


def prepare(context: stages.RunContext[portset.HostPorts]) -> builder_test_stage.BuilderTest:
    ports = context.ports
    root = context.facts[composition_keys.RUNTIME_ROOT]
    run = context.facts[composition_keys.RUN_ID]
    repository = context.facts[composition_keys.REPOSITORY]
    parent = context.facts[verifykeys.PARENT]
    lock = fingerprintpackages.load_lock(repository)
    _require_built_patch(
        ports, root, parent, lock, fingerprintpackages.patch_digests(ports, repository, lock)
    )
    files = {
        name: safepaths.SafePath(repository.path / name) for name in defaults.GTK_INPUT_FILES
    }
    archive_name, archive = _archive(root, parent, lock)
    inputs = {name: ports.digests.file(path).hex for name, path in files.items()}
    inputs[f"{defaults.FINGERPRINT_INPUTS_DIRECTORY}/{archive_name}"] = (
        ports.digests.file(archive).hex
    )
    request = exports.inside(root, run, defaults.GTK_REQUEST_NAME)
    ports.files.write_atomic(
        request, encoding.canonical({"parent_build": str(parent), "inputs": inputs}) + b"\n",
        mode=defaults.RECORD_MODE,
    )
    remote = safepaths.RemotePath(f"{WORK_PREFIX}{run}")
    return builder_test_stage.BuilderTest(
        remote=remote,
        deliveries=(
            *((path, remote.joined(name)) for name, path in files.items()),
            (archive, remote.joined(f"{defaults.FINGERPRINT_INPUTS_DIRECTORY}/{archive_name}")),
            (request, remote.joined(defaults.GTK_REQUEST_NAME)),
        ),
        script=guestshell.RemoteScript.of(
            guestshell.Step.of("cd", str(remote)),
            guestshell.Step.of("flock", "-n", defaults.GTK_LOCK_NAME, "python3", RUNNER),
        ),
        transcript=defaults.GTK_LOG_NAME,
        inputs=inputs,
    )


def judge(
    ports: portset.HostPorts,
    root: safepaths.RuntimeRoot,
    home: safepaths.SafePath,
    test: builder_test_stage.BuilderTest,
    document: encoding.Document,
) -> str | None:
    try:
        report = fingerprintpackages.parse_gtk_report(document)
        fingerprintpackages.require_gtk_logs(ports, root, home, report)
    except errors.Refusal as refusal:
        return refusal.subject
    return fingerprintpackages.judge_gtk(report, test.inputs)


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
