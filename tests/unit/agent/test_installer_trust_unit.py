"""The trust fixture signs a scratch image, verifies it, and refuses every wrong way to trust it."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from apex.adapters.fakes import (
    fake_archives,
    fake_blockdevices,
    fake_clock,
    fake_containers,
    fake_digesting,
    fake_extents,
    fake_files,
    fake_ids,
    fake_process,
)
from apex.agent import agentports, builder
from apex.agent.units import installer_trust_unit
from apex.config import defaults
from apex.kernel import errors, quantities, refusals, safepaths
from apex.ports import containers
from apex.trust import preflight

WORK = "/var/tmp/apex-trust-" + "a" * 32
PRIVATE = quantities.FileMode(0o600)
REJECTING = {
    "wrong-policy.json", "wrong-identity-policy.json", "unsigned-policy.json",
    "tampered-signature-policy.json", "tampered-manifest-policy.json",
    "unexpected-source-policy.json",
}
EXPECTED_CASES = {
    "signed-roundtrip", "same-store-preflight", "wrong-key", "wrong-identity", "unsigned",
    "tampered-signature", "tampered-manifest", "unexpected-source",
}


class Proxy:
    """Stands in for the verbatim program's proxy check; rejects under the rejecting policies."""

    def __init__(self) -> None:
        self.opened: list[tuple[str, str]] = []

    def verified_open(self, source: str, policy: Path) -> dict[str, object]:
        self.opened.append((source, policy.name))
        if policy.name in REJECTING:
            raise RuntimeError(f"Signature rejected by policy {policy.name}")
        return {"protocol": "0.2.8", "method": "OpenImage", "source": source}


@pytest.fixture
def proxy(monkeypatch: pytest.MonkeyPatch) -> Proxy:
    stand_in = Proxy()
    loaded = preflight.load()
    monkeypatch.setattr(loaded.program, "verified_open", stand_in.verified_open)
    monkeypatch.setattr(preflight, "load", lambda: loaded)
    monkeypatch.setattr(builder.os, "geteuid", lambda: 0)
    return stand_in


def engine(files: fake_files.MemoryFiles) -> fake_containers.FakeRegistry:
    registry = fake_containers.FakeRegistry()

    def on_copy(destination: containers.ImageReference) -> None:
        if destination.transport is containers.Transport.DIRECTORY:
            home = safepaths.SafePath(Path(destination.name))
            files.write_atomic(home / "manifest.json", b'{"schemaVersion": 2}', mode=PRIVATE)
            files.write_atomic(home / "signature-1", b"signed", mode=PRIVATE)

    def on_key(prefix: safepaths.SafePath) -> None:
        files.write_atomic(
            safepaths.SafePath(Path(f"{prefix}.pub")),
            b"public " + prefix.path.name.encode(),
            mode=PRIVATE,
        )
        files.write_atomic(safepaths.SafePath(Path(f"{prefix}.private")), b"private", mode=PRIVATE)

    registry.on_copy = on_copy
    registry.on_key = on_key
    for name in REJECTING:
        registry.rejections[name] = "signature rejected by policy"
    return registry


def bundle(*, store: str = "overlay /var/lib/containers/storage") -> tuple[
    fake_process.ScriptedProcess, fake_files.MemoryFiles, agentports.AgentPorts
]:
    process = fake_process.ScriptedProcess()
    process.expect(("systemd-detect-virt", "--vm"), fake_process.Reply(stdout=b"kvm\n"))
    process.expect(("skopeo", "--version"), fake_process.Reply(stdout=b"skopeo version 1.20\n"))
    process.expect(
        ("podman", "info", "--format", "{{.Store.GraphDriverName}} {{.Store.GraphRoot}}"),
        fake_process.Reply(stdout=f"{store}\n".encode()),
    )
    files = fake_files.MemoryFiles()
    files.write_atomic(
        safepaths.SafePath(Path(defaults.BUILDER_MARKER)),
        f"{defaults.BUILDER_MARKER_TEXT}\n".encode(), mode=PRIVATE,
    )
    files.write_atomic(
        safepaths.SafePath(Path(defaults.CONTAINER_POLICY)), b'{"default": [{"type": "reject"}]}',
        mode=PRIVATE,
    )
    ports = agentports.AgentPorts(
        processes=process, files=files, clock=fake_clock.ManualClock(),
        containers=engine(files), digests=fake_digesting.CountingDigests(),
        archives=fake_archives.MemoryArchives(), identities=fake_ids.SequenceIdentities(),
        extents=fake_extents.FakeExtents(), blocks=fake_blockdevices.FakeBlockDevices(),
    )
    return process, files, ports


def registry_of(ports: agentports.AgentPorts) -> fake_containers.FakeRegistry:
    assert isinstance(ports.containers, fake_containers.FakeRegistry)
    return ports.containers


def test_every_case_passes_and_the_report_is_written(proxy: Proxy) -> None:
    _, files, ports = bundle()

    report = installer_trust_unit.run(ports, arguments={"work": WORK})

    assert report["status"] == "PASS"
    assert report["cases"] == dict.fromkeys(EXPECTED_CASES, "PASS")
    assert report["proxy_cases"] == dict.fromkeys(EXPECTED_CASES, "PASS")
    assert report["skopeo_version"] == "skopeo version 1.20"
    assert isinstance(report["public_key_sha256"], dict)
    assert set(report["public_key_sha256"]) == {"trusted", "wrong"}
    results = safepaths.SafePath(Path(WORK) / "output" / "results.json")
    written = json.loads(files.read_bytes(results, limit=1 << 20))
    assert written["status"] == "PASS"
    registry = registry_of(ports)
    assert [request.tag for request in registry.builds] == [
        "localhost/apex-trust-fixture:" + "a" * 32
    ]
    assert registry.builds[0].layers is False and registry.builds[0].network_none is False
    assert [key.prefix.path.name for key in registry.keys] == ["trusted", "wrong"]
    assert [item[1] for item in proxy.opened] == [
        "trusted-policy.json", "trusted-policy.json", "wrong-policy.json",
        "wrong-identity-policy.json", "unsigned-policy.json", "tampered-signature-policy.json",
        "tampered-manifest-policy.json", "unexpected-source-policy.json",
    ]


def test_the_copies_run_in_the_older_order(proxy: Proxy) -> None:
    _, _, ports = bundle()

    installer_trust_unit.run(ports, arguments={"work": WORK})

    copies = registry_of(ports).copies
    tag = "localhost/apex-trust-fixture:" + "a" * 32
    verified = tag.replace("fixture:", "verified:")
    assert [(str(item.source), str(item.destination)) for item in copies[:4]] == [
        (f"containers-storage:{tag}", f"dir:{WORK}/signed"),
        (f"dir:{WORK}/signed", f"containers-storage:{verified}"),
        (f"containers-storage:{verified}", f"dir:{WORK}/verified-copy"),
        (
            f"containers-storage:{verified}",
            f"containers-storage:{tag.replace('fixture:', 'preflight:')}",
        ),
    ]
    assert copies[0].signing is not None and copies[0].signing.identity == tag
    assert [item.destination.name.rsplit("/", 1)[-1] for item in copies[4:]] == [
        "rejected-wrong-key", "rejected-wrong-identity", "rejected-unsigned",
        "rejected-tampered-signature", "rejected-tampered-manifest", "rejected-unexpected-source",
    ]


def test_the_unsigned_variant_carries_no_signature_and_the_tampered_manifest_is_marked(
    proxy: Proxy,
) -> None:
    _, files, ports = bundle()

    installer_trust_unit.run(ports, arguments={"work": WORK})

    work = Path(WORK)
    assert not files.exists(safepaths.SafePath(work / "unsigned" / "signature-1"))
    tampered = safepaths.SafePath(work / "tampered-signature" / "signature-1")
    assert files.read_bytes(tampered, limit=64) == b"Invalid synthetic signature\n"
    manifest = safepaths.SafePath(work / "tampered-manifest" / "manifest.json")
    assert json.loads(files.read_bytes(manifest, limit=1 << 16))["annotations"] == {
        "apex.test.tampered": "true"
    }


def test_a_negative_the_engine_accepts_refuses_the_run(proxy: Proxy) -> None:
    _, _, ports = bundle()
    registry_of(ports).rejections.pop("unsigned-policy.json")

    with pytest.raises(errors.Refusal) as caught:
        installer_trust_unit.run(ports, arguments={"work": WORK})

    assert caught.value.reason is refusals.RefusalReason.NEGATIVE_ACCEPTED


def test_a_negative_refused_for_another_reason_refuses_the_run(proxy: Proxy) -> None:
    _, _, ports = bundle()
    registry_of(ports).rejections["wrong-policy.json"] = "no space left on device"

    with pytest.raises(errors.Refusal) as caught:
        installer_trust_unit.run(ports, arguments={"work": WORK})

    assert caught.value.reason is refusals.RefusalReason.NEGATIVE_WRONG_REASON


def test_a_negative_the_proxy_opens_refuses_the_run(proxy: Proxy) -> None:
    _, _, ports = bundle()
    kept = set(REJECTING)
    REJECTING.discard("tampered-manifest-policy.json")
    try:
        with pytest.raises(errors.Refusal) as caught:
            installer_trust_unit.run(ports, arguments={"work": WORK})
    finally:
        REJECTING.update(kept)

    assert caught.value.reason is refusals.RefusalReason.NEGATIVE_ACCEPTED
    assert "opened by the proxy" in caught.value.subject


def test_another_container_store_is_refused_before_anything_is_built(proxy: Proxy) -> None:
    _, _, ports = bundle(store="vfs /home/builder/.local/share/containers/storage")

    with pytest.raises(errors.Refusal) as caught:
        installer_trust_unit.run(ports, arguments={"work": WORK})

    assert caught.value.reason is refusals.RefusalReason.FIXTURE_STATE_UNEXPECTED
    assert registry_of(ports).builds == []


def test_a_changed_system_policy_refuses_the_run(proxy: Proxy) -> None:
    _, files, ports = bundle()
    registry = registry_of(ports)
    original = registry.on_copy

    def on_copy(destination: containers.ImageReference) -> None:
        assert original is not None
        original(destination)
        files.write_atomic(
            safepaths.SafePath(Path(defaults.CONTAINER_POLICY)),
            b'{"default": [{"type": "insecureAcceptAnything"}]}',
            mode=PRIVATE,
        )

    registry.on_copy = on_copy

    with pytest.raises(errors.Refusal) as caught:
        installer_trust_unit.run(ports, arguments={"work": WORK})

    assert caught.value.reason is refusals.RefusalReason.FIXTURE_STATE_UNEXPECTED


@pytest.mark.parametrize("work", ["/tmp/elsewhere", "/var/tmp/apex-trust-short", 5])
def test_a_work_directory_that_is_not_named_for_a_run_is_refused(work: Any, proxy: Proxy) -> None:
    _, _, ports = bundle()

    with pytest.raises(errors.Refusal) as caught:
        installer_trust_unit.run(ports, arguments={"work": work})

    assert caught.value.reason is refusals.RefusalReason.REQUEST_MALFORMED
