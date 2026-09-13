"""The builder's storage made ready: base image, disk, key, seed and firmware variables.

Each piece is made once and left alone after: the base image is fetched only when the
runtime root does not hold it at the reviewed digest, the disk is a fresh layer over that
base at the size the settings say, the key pair is generated when absent, the seed is
written from the key's public half, and the firmware variables are copied from where the
host settings point. A running machine refuses the whole operation, as the older tool did.
"""

from __future__ import annotations

import dataclasses

from apex.config import defaults, loader
from apex.generating import builderseed
from apex.kernel import commands, encoding, errors, identifiers, refusals, safepaths
from apex.model import sourcelock
from apex.ports import portset
from apex.provisioning import backingchain, launching
from apex.trust import acquiring

KEYGEN = "ssh-keygen"


@dataclasses.dataclass(frozen=True, slots=True)
class Prepared:
    base: safepaths.SafePath
    base_fetched: bool
    disk_created: bool
    key_created: bool
    seed_created: bool
    variables_copied: bool

    def document(self) -> encoding.Document:
        return {
            "base": str(self.base),
            "base_fetched": self.base_fetched,
            "disk_created": self.disk_created,
            "key_created": self.key_created,
            "seed_created": self.seed_created,
            "variables_copied": self.variables_copied,
        }


def prepare(
    ports: portset.HostPorts,
    settings: loader.Settings,
    root: safepaths.RuntimeRoot,
    *,
    base: sourcelock.LockedSource,
    instance: identifiers.RunId,
) -> Prepared:
    running = launching.current(ports, root=root)
    if running is not None:
        raise errors.Refusal(
            refusals.RefusalReason.MACHINE_RUNNING,
            subject=f"a {running.intent.role} machine, process {running.identity.process}",
            remedy="stop it before preparing the builder's storage",
        )
    image = root.child(str(base.filename))
    fetched = _fetched(ports, image, base, root)
    chain = backingchain.require_standalone(backingchain.inspect(ports, image.path, root=root))
    disk = root.child(defaults.BUILDER_DISK_NAME)
    disk_created = not ports.files.exists(disk)
    if disk_created:
        backingchain.overlay(ports, chain, into=disk, root=root, size=settings.builder.disk)
    key = root.child(defaults.BUILDER_KEY_NAME)
    key_created = not ports.files.exists(key)
    if key_created:
        _generate_key(ports, key)
    seed_created = _seeded(ports, root, key, instance)
    variables = root.child(defaults.BUILDER_VARIABLES_NAME)
    copied = not ports.files.exists(variables)
    if copied:
        ports.files.copy(safepaths.SafePath(settings.builder.firmware_variables), variables)
    return Prepared(
        base=image, base_fetched=fetched, disk_created=disk_created, key_created=key_created,
        seed_created=seed_created, variables_copied=copied,
    )


def _fetched(
    ports: portset.HostPorts,
    image: safepaths.SafePath,
    base: sourcelock.LockedSource,
    root: safepaths.RuntimeRoot,
) -> bool:
    if acquiring.already_held(ports, image, expected=base.sha256, root=root):
        return False
    ports.downloads.fetch(
        base.url, into=image, expected=base.sha256, deadline=defaults.DOWNLOAD_DEADLINE
    )
    return True


def _generate_key(ports: portset.HostPorts, key: safepaths.SafePath) -> None:
    completed = ports.processes.run(
        commands.Argv.of(
            KEYGEN, "-q", "-t", defaults.BUILDER_KEY_TYPE, "-N", "", "-C",
            defaults.BUILDER_KEY_COMMENT, "-f", key,
        ),
        deadline=defaults.KEYGEN_DEADLINE,
        limit=commands.OutputLimit.default(),
    )
    if not completed.succeeded:
        raise errors.PortFailure(
            port=KEYGEN, cause=completed.stderr.decode(errors="replace").strip()
        )


def _seeded(
    ports: portset.HostPorts,
    root: safepaths.RuntimeRoot,
    key: safepaths.SafePath,
    instance: identifiers.RunId,
) -> bool:
    seed = root.child(defaults.BUILDER_SEED_NAME)
    if ports.files.exists(seed):
        return False
    public = ports.files.read_bytes(
        safepaths.SafePath(key.path.with_name(key.path.name + defaults.PUBLIC_KEY_SUFFIX)),
        limit=defaults.DOCUMENT_LIMIT.value,
    ).decode().strip()
    ports.files.write_atomic(
        root.child(defaults.USER_DATA_NAME), builderseed.user_data(public),
        mode=defaults.RECORD_MODE,
    )
    ports.files.write_atomic(
        root.child(defaults.META_DATA_NAME), builderseed.meta_data(instance),
        mode=defaults.RECORD_MODE,
    )
    ports.files.write_atomic(seed, builderseed.seed(public, instance), mode=defaults.RECORD_MODE)
    return True
