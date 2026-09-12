"""The typed wrapper says exactly what the verbatim program says, with the project's errors."""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import types
from pathlib import Path

import pytest

from apex.kernel import errors, refusals
from apex.trust import preflight

REPOSITORY = Path(__file__).resolve().parents[3]
KEY = b"synthetic public key for unit tests"


def older() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(
        "installer_preflight", REPOSITORY / "guest" / "installer-preflight.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def metadata(digest: str = "sha256:" + "a" * 64) -> dict[str, object]:
    return {
        "digest": digest,
        "image_id": "sha256:" + "c" * 64,
        "reference": "localhost/apex-payload@" + digest,
        "identity": "localhost/apex-payload:" + digest[7:],
        "purpose": "development-installer-only",
        "public_key_sha256": hashlib.sha256(KEY).hexdigest(),
    }


def test_the_policy_is_the_older_program_s_policy(tmp_path: Path) -> None:
    loaded = preflight.load()

    policy = loaded.signature_policy(metadata(), KEY, payload=tmp_path)

    assert policy == older().signature_policy(metadata(), KEY, payload=tmp_path)
    requirement = policy["transports"]["dir"][str(tmp_path)][0]  # type: ignore[index]
    assert requirement["keyData"] == base64.b64encode(KEY).decode()  # type: ignore[index]
    assert policy["default"] == [{"type": "reject"}]


@pytest.mark.parametrize(
    "field,value",
    [
        ("digest", "latest"),
        ("purpose", "release"),
        ("reference", "docker://unexpected/image:latest"),
        ("identity", "localhost/other:tag"),
        ("public_key_sha256", "0" * 64),
    ],
)
def test_a_contract_the_program_refuses_is_a_refusal_here(
    tmp_path: Path, field: str, value: str
) -> None:
    changed = metadata()
    changed[field] = value

    with pytest.raises(errors.Refusal) as caught:
        preflight.load().signature_policy(changed, KEY, payload=tmp_path)

    assert caught.value.reason is refusals.RefusalReason.PAYLOAD_CONTRACT_INVALID


def test_a_proxy_rejection_is_a_signature_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    loaded = preflight.load()

    def rejecting(source: str, policy: Path) -> dict[str, object]:
        raise RuntimeError(f"Signature rejected for {source} under {policy.name}")

    monkeypatch.setattr(loaded.program, "verified_open", rejecting)

    with pytest.raises(errors.Refusal) as caught:
        loaded.verified_open("dir:/payload", tmp_path / "policy.json")

    assert caught.value.reason is refusals.RefusalReason.SIGNATURE_REJECTED
    assert "policy.json" in caught.value.subject


def test_the_whole_verification_runs_over_a_payload_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = b"{}"
    layer = b"synthetic compressed layer bytes"
    config_digest = "sha256:" + hashlib.sha256(config).hexdigest()
    layer_digest = "sha256:" + hashlib.sha256(layer).hexdigest()
    raw = json.dumps({
        "config": {"digest": config_digest, "size": len(config)},
        "layers": [{"digest": layer_digest, "size": len(layer)}],
    }).encode()
    (tmp_path / config_digest[7:]).write_bytes(config)
    (tmp_path / layer_digest[7:]).write_bytes(layer)
    (tmp_path / "manifest.json").write_bytes(raw)
    digest = "sha256:" + hashlib.sha256(raw).hexdigest()
    document = metadata(digest)
    document["image_id"] = config_digest
    (tmp_path / "payload.json").write_text(json.dumps(document))
    (tmp_path / "payload.pub").write_bytes(KEY)
    loaded = preflight.load()
    policy = loaded.signature_policy(document, KEY, payload=tmp_path)
    (tmp_path / "policy.json").write_text(json.dumps(policy))
    monkeypatch.setattr(loaded.program, "verified_open", lambda *_: {"protocol": "0.2.8"})

    outcome = loaded.verify(tmp_path, tmp_path / "policy.json", payload=tmp_path)

    assert outcome["status"] == "PASS"
    assert outcome["digest"] == digest
    assert outcome["verified_blob_count"] == 2


def test_loading_executes_nothing_but_definitions() -> None:
    loaded = preflight.load()

    assert callable(loaded.program.signature_policy)
    assert callable(loaded.program.verify)
    assert loaded.program.__file__ == preflight.ASSET
