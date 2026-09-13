"""The facts the composition stages pass to one another, keyed so the reader knows the type."""

from __future__ import annotations

from apex.composition import accessgrant
from apex.config import sourcepins
from apex.kernel import commands, identifiers, safepaths
from apex.model import builds, oci
from apex.pipeline import facts
from apex.ports import archives, guestshell
from apex.trust import acquiring

REPOSITORY = facts.FactKey[safepaths.SourceRoot]("repository")
RUNTIME_ROOT = facts.FactKey[safepaths.RuntimeRoot]("runtime.root")
RUN_ID = facts.FactKey[identifiers.RunId]("run.id")
SOURCE_SET = facts.FactKey[archives.SourceSet]("source.set")
SOURCE_BUNDLE = facts.FactKey[archives.SourceBundle]("source.bundle")
SOURCE_MANIFEST = facts.FactKey[identifiers.Digest]("source.manifest")

BUILDER = facts.FactKey[guestshell.GuestTarget]("builder")
BUILDER_VERIFIED = facts.FactKey[guestshell.GuestTarget]("builder.verified")
REQUESTED_PROFILE = facts.FactKey[builds.Profile]("build.requested-profile")
BUILD_PROFILE = facts.FactKey[builds.Profile]("build.profile")
KIND = facts.FactKey[builds.ArtifactKind]("build.kind")
PARENT = facts.FactKey[identifiers.BuildId | None]("build.parent")
FROZEN = facts.FactKey[oci.FrozenImage | None]("build.frozen")
REVIEWED_LOCK = facts.FactKey[sourcepins.ReviewedLock]("sources.reviewed")
SOURCES = facts.FactKey[acquiring.Acquisition]("sources.acquired")
REMOTE = facts.FactKey[safepaths.RemotePath]("guest.remote")
TRANSFERRED = facts.FactKey[tuple[safepaths.RemotePath, ...]]("guest.transferred")
BUILD_RUN = facts.FactKey[commands.CompletedRun]("build.run")
RETRIEVED = facts.FactKey[bool]("build.retrieved")
BUILD_RECORD = facts.FactKey[builds.BuildRecord]("build.record")
TEST_ACCESS = facts.FactKey[bool]("build.test-access")
ACCESS = facts.FactKey[accessgrant.Granted | None]("build.access")
