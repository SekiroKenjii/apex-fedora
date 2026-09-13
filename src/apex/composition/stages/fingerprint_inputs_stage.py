"""Bind the tested packages to the image build before anything is sent to the builder.

The parent's output must verify against the builder's development key and be the frozen
image; the dialog test must have passed with its logs intact and its patch the checkout's;
the package build must be a passed build of the same patch whose three image packages
digest to what it reported. The request written beside the run names all of it by digest.
"""

from __future__ import annotations

from apex.composition import artifactchecks, exports, fingerprintpackages, keys
from apex.config import defaults
from apex.kernel import encoding, errors, identifiers, refusals, safepaths
from apex.model import builds, oci
from apex.pipeline import effects, stages
from apex.ports import portset
from apex.trust import anchors, verifying

OUTPUT = builds.OUTPUT_DIRECTORY


def development_anchor(root: safepaths.RuntimeRoot) -> anchors.TrustAnchor:
    """The builder's development key as the runtime root keeps it, refused when absent."""
    key = root.child(f"{defaults.TRUST_DIRECTORY}/{defaults.DEVELOPMENT_KEY_NAME}")
    if not key.path.is_file():
        raise errors.Refusal(
            refusals.RefusalReason.PATH_NOT_A_REGULAR_FILE,
            subject=str(key),
            remedy="fetch the builder's development key first",
        )
    return anchors.TrustAnchor(
        public_key=safepaths.RegularFile.adopt(key.path), provenance=anchors.Provenance.BUILDER_SSH
    )


def _require_signed_parent(
    ports: portset.HostPorts,
    root: safepaths.RuntimeRoot,
    parent: identifiers.BuildId,
    frozen: oci.FrozenImage,
) -> None:
    verified = verifying.verify_bundle(
        ports,
        location=verifying.BundleLocation(
            root=root, relative=f"{defaults.EXPORT_DIRECTORY}/{parent}/{OUTPUT}"
        ),
        anchor=development_anchor(root),
    )
    if verified.digest != frozen.digest or frozen.profile != str(builds.Profile.FEDORA):
        raise errors.Refusal(
            refusals.RefusalReason.FINGERPRINT_INPUT_MISMATCH,
            subject="the parent is not the signed frozen control image",
        )


def _read(ports: portset.HostPorts, path: safepaths.SafePath) -> dict[str, encoding.JsonValue]:
    return encoding.parse_object(ports.files.read_bytes(path, limit=defaults.DOCUMENT_LIMIT.value))


def _rpms(
    ports: portset.HostPorts,
    root: safepaths.RuntimeRoot,
    report: fingerprintpackages.RpmBuildReport,
    home: safepaths.SafePath,
    lock: fingerprintpackages.PackageLock,
) -> dict[str, identifiers.Digest]:
    found: dict[str, identifiers.Digest] = {}
    for name in fingerprintpackages.image_rpms(lock):
        relative = f"{defaults.FINGERPRINT_PACKAGES_DIRECTORY}/{name}"
        artifactchecks.require_artifacts(
            ports, root, home, {relative: report.artifacts.get(relative, "")}
        )
        found[name] = identifiers.Digest(report.artifacts[relative])
    return found


def bind(context: stages.RunContext[portset.HostPorts]) -> fingerprintpackages.Request:
    ports = context.ports
    root = context.facts[keys.RUNTIME_ROOT]
    parent, frozen = context.facts[keys.PARENT], context.facts[keys.FROZEN]
    if parent is None or frozen is None:
        raise errors.InternalDefect("the fingerprint image is derived from a frozen parent")
    _require_signed_parent(ports, root, parent, frozen)
    lock = fingerprintpackages.load_lock(context.facts[keys.REPOSITORY])
    patches = fingerprintpackages.patch_digests(ports, context.facts[keys.REPOSITORY], lock)
    gtk_home = exports.inside(root, context.facts[keys.GTK_TEST], OUTPUT)
    gtk = fingerprintpackages.parse_gtk_report(_read(ports, gtk_home / defaults.RESULTS_NAME))
    fingerprintpackages.require_gtk_logs(ports, root, gtk_home, gtk)
    rpm_home = exports.inside(root, context.facts[keys.RPM_BUILD], OUTPUT)
    report = fingerprintpackages.parse_rpm_report(
        _read(ports, rpm_home / defaults.RESULTS_NAME), lock, patches
    )
    settings_patch = patches[fingerprintpackages.SETTINGS].hex
    if gtk.patch != settings_patch or report.patches[fingerprintpackages.SETTINGS] != gtk.patch:
        raise errors.Refusal(
            refusals.RefusalReason.FINGERPRINT_INPUT_MISMATCH,
            subject="the tested patch differs from the built package or the checkout",
        )
    return fingerprintpackages.Request(
        rpm_build=context.facts[keys.RPM_BUILD],
        gtk_test=context.facts[keys.GTK_TEST],
        gtk_report=ports.digests.file(gtk_home / defaults.RESULTS_NAME),
        rpms=_rpms(ports, root, report, rpm_home, lock),
    )


def apply(context: stages.RunContext[portset.HostPorts]) -> stages.StageResult:
    try:
        request = bind(context)
    except errors.Refusal as refusal:
        return stages.Refuse(reason=refusal.reason, detail=refusal.subject)
    except (errors.PortFailure, ValueError) as failure:
        return stages.Fail(cause=str(failure))
    context.ports.files.write_atomic(
        exports.inside(
            context.facts[keys.RUNTIME_ROOT],
            context.facts[keys.RUN_ID],
            defaults.FINGERPRINT_REQUEST_NAME,
        ),
        encoding.canonical(request.document()) + b"\n",
        mode=defaults.RECORD_MODE,
    )
    return stages.Advance(facts={keys.FINGERPRINT_REQUEST: request})


STAGE = stages.SimpleStage(
    id=identifiers.StageId("fingerprint.inputs"),
    reads=(
        keys.PARENT,
        keys.FROZEN,
        keys.RPM_BUILD,
        keys.GTK_TEST,
        keys.REPOSITORY,
        keys.RUNTIME_ROOT,
        keys.RUN_ID,
    ),
    writes=(keys.FINGERPRINT_REQUEST,),
    attests=frozenset(),
    effects=frozenset({effects.Effect.READS_HOST, effects.Effect.WRITES_RUNTIME}),
    preflight=stages.always_ready,
    apply=apply,
)
