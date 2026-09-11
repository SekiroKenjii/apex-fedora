"""The facts the composition stages pass to one another, keyed so the reader knows the type."""

from __future__ import annotations

from apex.kernel import identifiers, safepaths
from apex.pipeline import facts
from apex.ports import archives

REPOSITORY = facts.FactKey[safepaths.SourceRoot]("repository")
RUNTIME_ROOT = facts.FactKey[safepaths.RuntimeRoot]("runtime.root")
RUN_ID = facts.FactKey[identifiers.RunId]("run.id")
SOURCE_SET = facts.FactKey[archives.SourceSet]("source.set")
SOURCE_BUNDLE = facts.FactKey[archives.SourceBundle]("source.bundle")
SOURCE_MANIFEST = facts.FactKey[identifiers.Digest]("source.manifest")
