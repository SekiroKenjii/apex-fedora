"""Record what was bundled beside the archive, so the build input can be checked later."""

from __future__ import annotations

from apex.composition import keys
from apex.config import defaults
from apex.kernel import encoding, identifiers
from apex.pipeline import effects, stages
from apex.ports import archives, portset


def manifest(bundle: archives.SourceBundle) -> encoding.Document:
    return {
        "archive_sha256": bundle.archive_digest.hex,
        "merkle_root": bundle.merkle_root.hex,
        "files": {entry.path: entry.digest.hex for entry in bundle.files},
    }


def apply(context: stages.RunContext[portset.HostPorts]) -> stages.StageResult:
    run_id = context.facts[keys.RUN_ID]
    target = context.facts[keys.RUNTIME_ROOT].child(
        f"{defaults.EXPORT_DIRECTORY}/{run_id}/{defaults.SOURCE_MANIFEST_NAME}"
    )
    digest = context.ports.files.write_atomic(
        target,
        encoding.canonical(manifest(context.facts[keys.SOURCE_BUNDLE])),
        mode=defaults.RECORD_MODE,
    )
    return stages.Advance(facts={keys.SOURCE_MANIFEST: digest})


STAGE = stages.SimpleStage(
    id=identifiers.StageId("source.manifest"),
    reads=(keys.RUN_ID, keys.RUNTIME_ROOT, keys.SOURCE_BUNDLE),
    writes=(keys.SOURCE_MANIFEST,),
    attests=frozenset(),
    effects=frozenset({effects.Effect.WRITES_RUNTIME}),
    preflight=stages.always_ready,
    apply=apply,
)
