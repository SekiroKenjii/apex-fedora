"""Exercise the real signature checks with a synthetic image in the isolated builder.

This is `guest/test-installer-trust.py` through the engine port: a scratch image built and
signed with a fixture key, copied under the policy the trust contract implies, opened through
the same proxy check the installer's preflight uses, and then every wrong way to trust it
tried and refused. A negative that is accepted, or refused for another reason, refuses the
whole run. The builder's own policy must be untouched at the end.
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Mapping
from pathlib import Path

from apex.agent import agentports, builder, units, worksites
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
from apex.ports import containers
from apex.provisioning.fixtures import update_fixture
from apex.trust import preflight

PASS = "PASS"
FAIL = "FAIL"
SCOPE = "synthetic image in builder VM, not Apex installer acceptance"
WORK_PREFIX = defaults.TRUST_WORK_PREFIX
TAG_PREFIX = "localhost/apex-trust-fixture:"
UNEXPECTED_IDENTITY = "localhost/apex-unexpected:fixture"
EXPECTED_STORE = ["overlay", "/var/lib/containers/storage"]
CONTAINERFILE = "FROM scratch\nCOPY payload.txt /payload.txt\n"
PAYLOAD_TEXT = "Apex signature fixture; not an operating system.\n"
INVALID_SIGNATURE = b"Invalid synthetic signature\n"
TAMPERED_ANNOTATION = "apex.test.tampered"
SIGNATURE_PREFIX = "signature-"
REJECTION = "signature|rejected by policy|digest.*match"
DIRECTORY_MODE = quantities.FileMode(0o700)
PRIVATE = quantities.FileMode(0o600)
KEY_NAMES = ("trusted", "wrong")
COPIED_VARIANTS = ("unsigned", "tampered-signature", "tampered-manifest", "unexpected-source")
VERSION = commands.Argv.of("skopeo", "--version")
STORE = commands.Argv.of(
    "podman", "info", "--format", "{{.Store.GraphDriverName}} {{.Store.GraphRoot}}"
)


@dataclasses.dataclass(frozen=True, slots=True)
class Site:
    root: safepaths.SafePath
    output: safepaths.SafePath
    tag: str
    passphrase: safepaths.SafePath

    @property
    def verified_tag(self) -> str:
        return self.tag.replace("fixture:", "verified:")

    @property
    def preflight_tag(self) -> str:
        return self.tag.replace("fixture:", "preflight:")

    @property
    def signed(self) -> safepaths.SafePath:
        return self.root / "signed"

    def key(self, name: str) -> safepaths.SafePath:
        return self.root / f"{name}.pub"

    def private_key(self, name: str) -> safepaths.SafePath:
        return self.root / f"{name}.private"


@dataclasses.dataclass(slots=True)
class Report:
    cases: dict[str, encoding.JsonValue] = dataclasses.field(default_factory=dict)
    proxy_cases: dict[str, encoding.JsonValue] = dataclasses.field(default_factory=dict)
    facts: dict[str, encoding.JsonValue] = dataclasses.field(default_factory=dict)


def _unexpected(detail: str) -> errors.Refusal:
    return errors.Refusal(refusals.RefusalReason.FIXTURE_STATE_UNEXPECTED, subject=detail)


def _run(ports: agentports.AgentPorts, argv: commands.Argv) -> str:
    completed = ports.processes.run(
        argv, deadline=defaults.ENGINE_QUERY_DEADLINE, limit=commands.OutputLimit.default()
    )
    if not completed.succeeded:
        raise errors.PortFailure(
            port="process", cause=f"{argv.arguments[0]} exited with {completed.exit_code}"
        )
    return completed.stdout.decode(errors="replace")


def _read(ports: agentports.AgentPorts, path: safepaths.SafePath) -> bytes:
    return ports.files.read_bytes(path, limit=defaults.DOCUMENT_LIMIT.value)


def _digest(ports: agentports.AgentPorts, path: safepaths.SafePath) -> identifiers.Digest:
    """Every file hashed here is a policy, a key or a manifest, read whole through the port."""
    return hashing.digest_bytes(_read(ports, path))


def _save(
    ports: agentports.AgentPorts, path: safepaths.SafePath, value: encoding.JsonValue
) -> None:
    ports.files.write_atomic(path, encoding.canonical(value) + b"\n", mode=PRIVATE)


def _site(arguments: Mapping[str, encoding.JsonValue]) -> tuple[safepaths.SafePath, str]:
    site, run_id = worksites.site_of(arguments, prefix=WORK_PREFIX)
    return site, str(run_id)


def _requirement(site: Site, *, key: str, identity: str) -> list[encoding.JsonValue]:
    return [
        {
            "type": "sigstoreSigned",
            "keyPath": str(site.key(key)),
            "signedIdentity": {"type": "exactReference", "dockerReference": identity},
        }
    ]


def _policy(
    ports: agentports.AgentPorts,
    site: Site,
    path: safepaths.SafePath,
    source_directory: safepaths.SafePath,
    *,
    key: str = "trusted",
    identity: str | None = None,
) -> safepaths.SafePath:
    requirement = _requirement(site, key=key, identity=identity or site.tag)
    _save(
        ports,
        path,
        {
            "default": [{"type": "reject"}],
            "transports": {
                "dir": {str(source_directory): requirement},
                "containers-storage": {
                    f"{update_fixture.STORAGE_SCOPE}{site.verified_tag}": requirement
                },
            },
        },
    )
    return path


def _directory(path: safepaths.SafePath) -> containers.ImageReference:
    return containers.ImageReference(containers.Transport.DIRECTORY, str(path))


def _prepare(ports: agentports.AgentPorts, site: Site, report: Report) -> None:
    report.facts["skopeo_version"] = _run(ports, VERSION).strip()
    if _run(ports, STORE).split() != EXPECTED_STORE:
        raise _unexpected("review the fixture policy for this container store")
    context = site.root / "context"
    ports.files.make_directory(context, mode=DIRECTORY_MODE)
    ports.files.write_atomic(context / "Containerfile", CONTAINERFILE.encode(), mode=PRIVATE)
    ports.files.write_atomic(context / "payload.txt", PAYLOAD_TEXT.encode(), mode=PRIVATE)
    ports.containers.build(
        containers.BuildRequest(context=context, tag=site.tag, network_none=False, layers=False)
    )
    ports.files.write_atomic(
        site.passphrase, f"{ports.identities.token()}\n".encode(), mode=PRIVATE
    )
    digests: dict[str, encoding.JsonValue] = {}
    for name in KEY_NAMES:
        ports.containers.generate_sigstore_key(prefix=site.root / name, passphrase=site.passphrase)
        ports.files.copy(site.key(name), site.output / f"{name}.pub")
        digests[name] = _digest(ports, site.output / f"{name}.pub").hex
    report.facts["public_key_sha256"] = digests


def _sign_and_verify(
    ports: agentports.AgentPorts, site: Site, report: Report
) -> safepaths.SafePath:
    signing = site.root / "signing-policy.json"
    _save(ports, signing, update_fixture.signing_policy(site.tag))
    ports.containers.copy(
        containers.ImageReference.stored(site.tag),
        _directory(site.signed),
        policy=signing,
        signing=containers.SigstoreSigning(
            private_key=site.private_key("trusted"), passphrase=site.passphrase, identity=site.tag
        ),
    )
    trusted = _policy(ports, site, site.root / "trusted-policy.json", site.signed)
    ports.containers.copy(
        _directory(site.signed),
        containers.ImageReference.stored(site.verified_tag),
        policy=trusted,
        signing=None,
    )
    ports.containers.copy(
        containers.ImageReference.stored(site.verified_tag),
        _directory(site.root / "verified-copy"),
        policy=trusted,
        signing=None,
    )
    digest = _digest(ports, site.signed / "manifest.json")
    if _digest(ports, site.root / "verified-copy" / "manifest.json") != digest:
        raise _unexpected("the verified copy's manifest differs from the signed one")
    report.facts["manifest_digest"] = str(digest)
    report.cases["signed-roundtrip"] = PASS
    proxy = preflight.load()
    verified = f"{containers.Transport.STORAGE}:{site.verified_tag}"
    report.facts["proxy_verification"] = proxy.verified_open(verified, trusted.path)
    report.proxy_cases["signed-roundtrip"] = PASS
    ports.containers.copy(
        containers.ImageReference.stored(site.verified_tag),
        containers.ImageReference.stored(site.preflight_tag),
        policy=trusted,
        signing=None,
    )
    report.cases["same-store-preflight"] = PASS
    proxy.verified_open(verified, trusted.path)
    report.proxy_cases["same-store-preflight"] = PASS
    return trusted


def _reject(
    ports: agentports.AgentPorts,
    site: Site,
    report: Report,
    name: str,
    source: containers.ImageReference,
    policy: safepaths.SafePath,
    pattern: str,
) -> None:
    try:
        ports.containers.copy(
            source, _directory(site.root / f"rejected-{name}"), policy=policy, signing=None
        )
    except errors.PortFailure as failure:
        if re.search(pattern, failure.cause, re.IGNORECASE) is None:
            raise errors.Refusal(
                refusals.RefusalReason.NEGATIVE_WRONG_REASON, subject=f"{name}: {failure.cause}"
            ) from failure
    else:
        raise errors.Refusal(
            refusals.RefusalReason.NEGATIVE_ACCEPTED, subject=f"{name} was copied under its policy"
        )
    report.cases[name] = PASS
    try:
        preflight.load().verified_open(str(source), policy.path)
    except errors.Refusal as refusal:
        if refusal.reason is not refusals.RefusalReason.SIGNATURE_REJECTED:
            raise
        if re.search(pattern, refusal.subject, re.IGNORECASE) is None:
            raise errors.Refusal(
                refusals.RefusalReason.NEGATIVE_WRONG_REASON, subject=f"{name}: {refusal.subject}"
            ) from refusal
    else:
        raise errors.Refusal(
            refusals.RefusalReason.NEGATIVE_ACCEPTED, subject=f"{name} was opened by the proxy"
        )
    report.proxy_cases[name] = PASS


def _copy_tree(
    ports: agentports.AgentPorts, source: safepaths.SafePath, destination: safepaths.SafePath
) -> None:
    ports.files.make_directory(destination, mode=DIRECTORY_MODE)
    for entry in ports.files.list_tree(source):
        if entry.kind is entry.kind.DIRECTORY:
            ports.files.make_directory(destination / entry.relative, mode=DIRECTORY_MODE)
        else:
            ports.files.copy(source / entry.relative, destination / entry.relative)


def _signature_names(ports: agentports.AgentPorts, directory: safepaths.SafePath) -> list[str]:
    return sorted(
        entry.relative
        for entry in ports.files.list_directory(directory)
        if entry.relative.startswith(SIGNATURE_PREFIX)
    )


def _tamper(
    ports: agentports.AgentPorts, name: str, destination: safepaths.SafePath, signatures: list[str]
) -> None:
    if name == "unsigned":
        for filename in signatures:
            ports.files.remove(destination / filename)
    elif name == "tampered-signature":
        ports.files.write_atomic(destination / signatures[0], INVALID_SIGNATURE, mode=PRIVATE)
    elif name == "tampered-manifest":
        manifest = encoding.parse_object(_read(ports, destination / "manifest.json"))
        annotations = manifest.get("annotations")
        held = dict(annotations) if isinstance(annotations, dict) else {}
        held[TAMPERED_ANNOTATION] = "true"
        manifest["annotations"] = held
        _save(ports, destination / "manifest.json", manifest)


def _negatives(ports: agentports.AgentPorts, site: Site, report: Report) -> None:
    verified = containers.ImageReference.stored(site.verified_tag)
    wrong = _policy(ports, site, site.root / "wrong-policy.json", site.signed, key="wrong")
    _reject(ports, site, report, "wrong-key", verified, wrong, "signature")
    wrong_identity = _policy(
        ports,
        site,
        site.root / "wrong-identity-policy.json",
        site.signed,
        identity=UNEXPECTED_IDENTITY,
    )
    _reject(
        ports,
        site,
        report,
        "wrong-identity",
        verified,
        wrong_identity,
        "identity|reference|signature",
    )
    signatures = _signature_names(ports, site.signed)
    if not signatures:
        raise _unexpected("signed fixture has no signature files")
    for name in COPIED_VARIANTS:
        destination = site.root / name
        _copy_tree(ports, site.signed, destination)
        policy = _policy(
            ports,
            site,
            site.root / f"{name}-policy.json",
            destination if name != "unexpected-source" else site.signed,
        )
        _tamper(ports, name, destination, signatures)
        _reject(ports, site, report, name, _directory(destination), policy, REJECTION)


def run(
    ports: agentports.AgentPorts, *, arguments: Mapping[str, encoding.JsonValue]
) -> encoding.Document:
    builder.require_isolated(ports)
    root, run_id = _site(arguments)
    site = Site(
        root=root,
        output=root / "output",
        tag=f"{TAG_PREFIX}{run_id}",
        passphrase=root / "passphrase",
    )
    ports.files.make_directory(site.output, mode=DIRECTORY_MODE)
    system_policy = safepaths.SafePath(Path(defaults.CONTAINER_POLICY))
    policy_before = _digest(ports, system_policy)
    report = Report()
    _prepare(ports, site, report)
    _sign_and_verify(ports, site, report)
    _negatives(ports, site, report)
    if _digest(ports, system_policy) != policy_before:
        raise _unexpected("the builder's system policy changed during the fixture")
    document: encoding.Document = {
        "status": PASS,
        "scope": SCOPE,
        "work_directory": str(site.root),
        "cases": dict(report.cases),
        "proxy_cases": dict(report.proxy_cases),
        "unchanged_system_policy_sha256": policy_before.hex,
        **report.facts,
    }
    _save(ports, site.output / "results.json", document)
    return document


units.declare(units.Unit(id=identifiers.ProbeId("fault.installer-trust"), run=run))
