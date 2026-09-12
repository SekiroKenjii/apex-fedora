"""Two signed images over the frozen payload, and every way a bad copy of them can be wrong.

The steps are the older `update-fixture.py` in order, each through a port: the storage
check, the payload's manifest against the frozen digest, two signing keys, the build context,
image A over the payload and B over A, each linted and its packages compared with the
baseline, each copied out signed, then the unsigned, untrusted and wrong-key variants, and
the bundle packed for the host. The older report embedded every command's output; this one
names the images, the files and the digests, and the engine's words go to the transcript.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from pathlib import Path

from apex.agent import agentports, builder, units
from apex.config import defaults
from apex.kernel import (
    commands,
    encoding,
    errors,
    hashing,
    identifiers,
    quantities,
    refusals,
    safepaths,
)
from apex.model import oci
from apex.ports import containers
from apex.provisioning.fixtures import update_fixture

DIRECTORY_MODE = quantities.FileMode(0o700)
PRIVATE = quantities.FileMode(0o600)
PLAIN = quantities.FileMode(0o644)
WORK_PREFIX = "/var/tmp/apex-update-"


@dataclasses.dataclass(frozen=True, slots=True)
class Keys:
    passphrase: safepaths.SafePath
    trusted_public: safepaths.SafePath
    trusted_private: safepaths.SafePath
    wrong_private: safepaths.SafePath


@dataclasses.dataclass(frozen=True, slots=True)
class Site:
    root: safepaths.SafePath
    run: identifiers.RunId
    output: safepaths.SafePath
    context: safepaths.SafePath
    bundle: safepaths.SafePath
    keys: Keys
    greenboot: identifiers.Digest


def run(
    ports: agentports.AgentPorts, *, arguments: Mapping[str, encoding.JsonValue]
) -> encoding.Document:
    builder.require_isolated(ports)
    root, run_id = _site_of(arguments)
    output = root / "output"
    ports.files.make_directory(output, mode=DIRECTORY_MODE)
    _storage_preflight(ports, root)
    frozen = oci.FrozenImage.parse(_read(ports, root / "target-image.json"))
    parent = f"{update_fixture.PAYLOAD_PREFIX}{frozen.digest.hex}"
    raw = ports.containers.manifest(containers.ImageReference.stored(parent))
    if hashing.digest_bytes(raw) != frozen.digest:
        raise errors.Refusal(
            refusals.RefusalReason.FROZEN_IMAGE_MISMATCH,
            subject="parent manifest differs from the frozen artifact",
        )
    keys = _keys(ports, root)
    site = Site(
        root=root, run=run_id, output=output, context=root / "context", bundle=root / "bundle",
        keys=keys, greenboot=_context(ports, root, run_id, keys),
    )
    ports.files.make_directory(site.bundle, mode=DIRECTORY_MODE)
    ports.files.copy(site.context / "policy.json", site.bundle / "policy.json")
    ports.files.copy(keys.trusted_public, output / "trusted.pub")
    policy_before = ports.digests.file(safepaths.SafePath(Path(update_fixture.BUILDER_POLICY)))
    baseline = _rpms(ports, parent)
    ports.files.write_atomic(output / "rpms.txt", baseline.encode(), mode=PLAIN)
    tags = {v: update_fixture.image_tag(run_id, v) for v in update_fixture.VERSIONS}
    images = {
        version: _build_version(ports, site, version, parent=parent, tags=tags, baseline=baseline)
        for version in update_fixture.VERSIONS
    }
    _share_identical_blobs(ports, site.bundle)
    _derive_cases(ports, site, tags["b"])
    return _finish(ports, site, frozen, images, policy_before)


def _finish(
    ports: agentports.AgentPorts,
    site: Site,
    frozen: oci.FrozenImage,
    images: Mapping[str, update_fixture.FixtureImage],
    policy_before: identifiers.Digest,
) -> encoding.Document:
    filesystem = _run(ports, "findmnt", "-n", "-o", "FSTYPE", "-T", str(site.root))
    files = {
        entry.relative: ports.digests.file(site.bundle / entry.relative).hex
        for entry in ports.files.list_tree(site.bundle)
        if entry.kind is not entry.kind.DIRECTORY
    }
    image_documents: dict[str, encoding.JsonValue] = {
        version: {
            "digest": str(image.digest), "config": str(image.config), "identity": image.identity,
        }
        for version, image in images.items()
    }
    public_key = ports.digests.file(site.keys.trusted_public).hex
    parent_document: encoding.Document = {
        "profile": frozen.profile, "digest": str(frozen.digest), "image_id": str(frozen.image_id),
    }
    ports.files.write_atomic(
        site.bundle / "fixture.json",
        encoding.canonical({
            "id": str(site.run), "parent": parent_document, "images": image_documents,
            "files": files, "public_key_sha256": public_key,
        }) + b"\n",
        mode=PLAIN,
    )
    archive = site.output / "payloads.tar"
    ports.archives.pack(site.bundle, into=archive, name=str(site.run))
    policy = safepaths.SafePath(Path(update_fixture.BUILDER_POLICY))
    if ports.digests.file(policy) != policy_before:
        raise _unexpected("builder policy changed")
    report: encoding.Document = {
        "status": "PASS",
        "id": str(site.run),
        "scope": update_fixture.SCOPE,
        "parent": parent_document,
        "images": image_documents,
        "greenboot_config_sha256": site.greenboot.hex,
        "public_key_sha256": public_key,
        "storage_sharing": {
            "filesystem": filesystem.stdout.decode(errors="replace").strip(),
            "files_removed": 0, "blobs": 0, "bytes_submitted": 0,
        },
        "files": files,
        "archive_sha256": ports.digests.file(archive).hex,
        "unchanged_builder_policy_sha256": policy_before.hex,
        "automatic_fallback": "NOT TESTED",
    }
    ports.files.write_atomic(
        site.output / "results.json", encoding.canonical(report) + b"\n", mode=PRIVATE
    )
    return report


def _storage_preflight(ports: agentports.AgentPorts, root: safepaths.SafePath) -> None:
    _run(ports, "sync", "-f", str(root))
    if ports.files.free_space(root) < update_fixture.REQUIRED_FREE.as_bytes():
        raise _unexpected(f"at least {update_fixture.REQUIRED_FREE.value} GiB free is required")


def _keys(ports: agentports.AgentPorts, root: safepaths.SafePath) -> Keys:
    passphrase = root / "passphrase"
    ports.files.write_atomic(
        passphrase, f"{ports.identities.token()}\n".encode(), mode=PRIVATE
    )
    for name in ("trusted", "wrong"):
        ports.containers.generate_sigstore_key(prefix=root / name, passphrase=passphrase)
    return Keys(
        passphrase=passphrase,
        trusted_public=root / "trusted.pub",
        trusted_private=root / "trusted.private",
        wrong_private=root / "wrong.private",
    )


def _context(
    ports: agentports.AgentPorts, root: safepaths.SafePath, run_id: identifiers.RunId, keys: Keys
) -> identifiers.Digest:
    context = root / "context"
    ports.files.make_directory(context, mode=DIRECTORY_MODE)
    ports.files.copy(root / update_fixture.GRUB_REPAIR, context / "fix-grub-fragment.py")
    preset = root / update_fixture.RETRY_PRESET
    if update_fixture.RETRY_LINE.encode() not in _read(ports, preset):
        raise _unexpected("recovery fixture requires the tested one-retry preset")
    ports.files.copy(preset, context / "greenboot.conf")
    policy = update_fixture.policy(_read(ports, keys.trusted_public), run_id)
    ports.files.write_atomic(
        context / "policy.json", encoding.canonical(policy) + b"\n", mode=PLAIN
    )
    return ports.digests.file(preset)


def _rpms(ports: agentports.AgentPorts, image: str) -> str:
    listing = _engine_run(
        ports,
        containers.RunRequest(
            image=image, argv=commands.Argv.of(*update_fixture.RPM_QUERY),
            read_only=True, network_none=True,
        ),
    )
    return "\n".join(sorted(listing.stdout.decode(errors="replace").splitlines())) + "\n"


def _build_version(
    ports: agentports.AgentPorts,
    site: Site,
    version: str,
    *,
    parent: str,
    tags: Mapping[str, str],
    baseline: str,
) -> update_fixture.FixtureImage:
    tag = tags[version]
    marker: encoding.Document = {"fixture": str(site.run), "version": version, "parent": parent}
    ports.files.write_atomic(
        site.context / "marker.json", encoding.canonical(marker) + b"\n", mode=PLAIN
    )
    recipe = update_fixture.containerfile(version, parent=parent, first=tags["a"])
    ports.files.write_atomic(site.context / "Containerfile", recipe.encode(), mode=PLAIN)
    ports.files.copy(site.context / "Containerfile", site.output / f"Containerfile.{version}")
    ports.containers.build(
        containers.BuildRequest(context=site.context, tag=tag, layers=False)
    )
    if _rpms(ports, tag) != baseline:
        raise _unexpected("fixture changed the RPM inventory")
    _engine_run(
        ports,
        containers.RunRequest(
            image=tag, argv=commands.Argv.of(*update_fixture.LINT), network_none=True
        ),
    )
    _check_recovery_configuration(ports, site, version, tag)
    signing_policy = site.root / "signing-policy.json"
    ports.files.write_atomic(
        signing_policy,
        encoding.canonical(update_fixture.signing_policy(tag)) + b"\n",
        mode=PLAIN,
    )
    destination = containers.ImageReference(
        containers.Transport.DIRECTORY, str(site.bundle / version)
    )
    ports.containers.copy(
        containers.ImageReference.stored(tag),
        destination,
        policy=signing_policy,
        signing=containers.SigstoreSigning(
            private_key=site.keys.trusted_private, passphrase=site.keys.passphrase, identity=tag
        ),
    )
    manifest = site.bundle / version / "manifest.json"
    payload = _read(ports, manifest)
    ports.files.copy(manifest, site.output / f"manifest-{version}.json")
    return update_fixture.FixtureImage(
        digest=identifiers.ImageId(hashing.digest_bytes(payload).hex),
        config=oci.config_digest(payload),
        identity=tag,
    )


def _check_recovery_configuration(
    ports: agentports.AgentPorts, site: Site, version: str, tag: str
) -> None:
    checks = _engine_run(
        ports,
        containers.RunRequest(
            image=tag, argv=commands.Argv.of(*update_fixture.RECOVERY_CHECK),
            read_only=True, network_none=True,
        ),
    ).stdout.decode(errors="replace")
    lines = checks.splitlines()[:2]
    if any(line.split()[0] != site.greenboot.hex for line in lines):
        raise _unexpected("packaged recovery preset differs from its source")
    ports.files.write_atomic(
        site.output / f"recovery-config-{version}.txt", checks.encode(), mode=PLAIN
    )


def _share_identical_blobs(ports: agentports.AgentPorts, bundle: safepaths.SafePath) -> None:
    # Share only immutable, content-addressed blobs. Signatures and manifests stay separate.
    for name in _blob_names(ports, bundle / "b"):
        blob = bundle / "b" / name
        peer = bundle / "a" / name
        if ports.files.exists(peer) and ports.digests.file(blob) == ports.digests.file(peer):
            ports.files.remove(blob)
            ports.files.link(peer, blob)


def _derive_cases(ports: agentports.AgentPorts, site: Site, tag_b: str) -> None:
    for case in update_fixture.CASES_FROM_B:
        _link_tree(ports, site.bundle / "b", site.bundle / case)
    for name in _signature_names(ports, site.bundle / "unsigned"):
        ports.files.remove(site.bundle / "unsigned" / name)
    wrong_signed = site.root / "wrong-signed"
    ports.containers.copy(
        containers.ImageReference.stored(tag_b),
        containers.ImageReference(containers.Transport.DIRECTORY, str(wrong_signed)),
        policy=site.root / "signing-policy.json",
        signing=containers.SigstoreSigning(
            private_key=site.keys.wrong_private, passphrase=site.keys.passphrase, identity=tag_b
        ),
    )
    wrong_key = site.bundle / "wrong-key"
    _link_tree(ports, site.bundle / "b", wrong_key)
    for name in _signature_names(ports, wrong_key):
        ports.files.remove(wrong_key / name)
    for name in _signature_names(ports, wrong_signed):
        ports.files.copy(wrong_signed / name, wrong_key / name)


def _link_tree(
    ports: agentports.AgentPorts, source: safepaths.SafePath, destination: safepaths.SafePath
) -> None:
    ports.files.make_directory(destination, mode=DIRECTORY_MODE)
    for entry in ports.files.list_tree(source):
        if entry.kind is entry.kind.DIRECTORY:
            ports.files.make_directory(destination / entry.relative, mode=DIRECTORY_MODE)
        else:
            ports.files.link(source / entry.relative, destination / entry.relative)


def _blob_names(ports: agentports.AgentPorts, directory: safepaths.SafePath) -> list[str]:
    return sorted(
        entry.relative
        for entry in ports.files.list_tree(directory)
        if "/" not in entry.relative and update_fixture.BLOB_NAME.fullmatch(entry.relative)
    )


def _signature_names(ports: agentports.AgentPorts, directory: safepaths.SafePath) -> list[str]:
    return sorted(
        entry.relative
        for entry in ports.files.list_tree(directory)
        if "/" not in entry.relative
        and entry.relative.startswith(update_fixture.SIGNATURE_PREFIX)
    )


def _engine_run(
    ports: agentports.AgentPorts, request: containers.RunRequest
) -> commands.CompletedRun:
    completed = ports.containers.run(request)
    if not completed.succeeded:
        raise errors.PortFailure(
            port="containers",
            cause=f"{request.argv.arguments[0]} in {request.image} exited with "
            f"{completed.exit_code}: {completed.stderr.decode(errors='replace').strip()}",
        )
    return completed


def _run(ports: agentports.AgentPorts, *argv: str) -> commands.CompletedRun:
    completed = ports.processes.run(
        commands.Argv.of(*argv),
        deadline=defaults.GUEST_COMMAND_DEADLINE,
        limit=commands.OutputLimit.default(),
    )
    if not completed.succeeded:
        raise errors.PortFailure(
            port="process",
            cause=f"{argv[0]} exited with {completed.exit_code}: "
            f"{completed.stderr.decode(errors='replace').strip()}",
        )
    return completed


def _read(ports: agentports.AgentPorts, path: safepaths.SafePath) -> bytes:
    return ports.files.read_bytes(path, limit=defaults.DOCUMENT_LIMIT.value)


def _site_of(
    arguments: Mapping[str, encoding.JsonValue],
) -> tuple[safepaths.SafePath, identifiers.RunId]:
    value = arguments.get("work")
    if not isinstance(value, str) or not value.startswith(WORK_PREFIX):
        raise errors.Refusal(
            refusals.RefusalReason.REQUEST_MALFORMED,
            subject=f"work must be a directory under {WORK_PREFIX}",
        )
    try:
        run_id = identifiers.RunId.parse(value.removeprefix(WORK_PREFIX))
    except errors.Refusal as fault:
        raise errors.Refusal(
            refusals.RefusalReason.REQUEST_MALFORMED, subject="work must be named for its run"
        ) from fault
    return safepaths.SafePath(Path(value)), run_id


def _unexpected(detail: str) -> errors.Refusal:
    return errors.Refusal(refusals.RefusalReason.FIXTURE_STATE_UNEXPECTED, subject=detail)


units.declare(units.Unit(id=identifiers.ProbeId("fixture.update"), run=run))
