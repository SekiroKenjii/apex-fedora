from __future__ import annotations

import json
from pathlib import Path

import pytest

from migration import runtime_inventory as inventory


@pytest.fixture
def root(tmp_path: Path) -> Path:
    base = tmp_path / "runtime"
    (base / "evidence").mkdir(parents=True)
    (base / "exports/build/test-access").mkdir(parents=True)
    (base / "evidence/boot.json").write_text('{"status": "PASS"}\n')
    (base / "candidate.json").write_text('{"digest": "sha256:aa"}\n')
    secret = base / "exports/build/test-access/credentials.json"
    secret.write_text("password\n")
    secret.chmod(0o600)
    (base / "link").symlink_to("candidate.json")
    return base


def manifest_of(root: Path, *, deep: bool = False) -> dict[str, object]:
    return inventory.build_manifest(root, deep=deep)


def entry_for(manifest: dict[str, object], path: str) -> dict[str, object]:
    for item in manifest["entries"]:  # type: ignore[union-attr]
        if item["path"] == path:
            return item
    raise AssertionError(f"No entry for {path}")


def test_secret_paths_are_never_digested(root: Path) -> None:
    entry = entry_for(manifest_of(root), "exports/build/test-access/credentials.json")

    assert entry["tier"] == "secret"
    assert "sha256" not in entry
    assert entry["mode"] == "0600"
    assert entry["size"] == len("password\n")


def test_ordinary_files_are_digested(root: Path) -> None:
    entry = entry_for(manifest_of(root), "evidence/boot.json")

    assert entry["tier"] == "digest"
    assert entry["sha256"]


def test_symlinks_record_their_target_and_are_not_followed(root: Path) -> None:
    entry = entry_for(manifest_of(root), "link")

    assert entry["tier"] == "symlink"
    assert entry["target"] == "candidate.json"
    assert "sha256" not in entry


def test_large_files_are_recorded_by_size_without_digesting(root: Path) -> None:
    big = root / "builder.qcow2"
    with big.open("wb") as handle:
        handle.truncate(inventory.LARGE_FILE_THRESHOLD + 1)

    entry = entry_for(manifest_of(root), "builder.qcow2")

    assert entry["tier"] == "stat"
    assert "sha256" not in entry
    assert entry["size"] == inventory.LARGE_FILE_THRESHOLD + 1


def test_deep_digests_large_files(root: Path) -> None:
    big = root / "builder.qcow2"
    with big.open("wb") as handle:
        handle.truncate(inventory.LARGE_FILE_THRESHOLD + 1)

    entry = entry_for(manifest_of(root, deep=True), "builder.qcow2")

    assert entry["sha256"]


def test_merkle_root_is_stable_across_repeated_runs(root: Path) -> None:
    assert manifest_of(root)["merkle_root"] == manifest_of(root)["merkle_root"]


@pytest.mark.parametrize(
    "mutate,expected_kind",
    [
        (lambda base: (base / "evidence/boot.json").write_text('{"status": "FAIL"}\n'), "sha256"),
        (lambda base: (base / "candidate.json").unlink(), "removed"),
        (lambda base: (base / "intruder.json").write_text("x\n"), "added"),
        (
            lambda base: (base / "exports/build/test-access/credentials.json").chmod(0o644),
            "mode",
        ),
        (lambda base: (base / "evidence/boot.json").write_text('{"status": "PASSS"}\n'), "size"),
    ],
)
def test_verify_detects_every_class_of_change(root: Path, mutate, expected_kind: str) -> None:
    before = manifest_of(root)

    mutate(root)
    differences = inventory.compare(before, manifest_of(root))

    assert [item.kind for item in differences if item.kind == expected_kind]


def test_an_unchanged_root_reports_no_differences(root: Path) -> None:
    before = manifest_of(root)

    assert inventory.compare(before, manifest_of(root)) == []


def test_record_writes_a_private_manifest(root: Path, tmp_path: Path) -> None:
    target = tmp_path / "state" / "inventory.json"

    assert inventory.record(root, target, deep=False) == 0
    assert target.stat().st_mode & 0o777 == 0o600
    assert json.loads(target.read_text())["merkle_root"]


def test_verify_refuses_a_shallow_run_against_a_deep_manifest(root: Path, tmp_path: Path) -> None:
    target = tmp_path / "inventory.json"
    inventory.record(root, target, deep=True)

    assert inventory.verify(root, target, deep=False) == 3


def test_verify_reports_a_missing_manifest(root: Path, tmp_path: Path) -> None:
    assert inventory.verify(root, tmp_path / "absent.json", deep=False) == 3


def test_recording_refuses_a_root_that_is_not_a_directory(tmp_path: Path) -> None:
    missing = tmp_path / "absent"

    assert inventory.main(["record", "--root", str(missing)]) == 3


def test_verifying_a_machine_with_no_root_is_not_a_finding(tmp_path: Path) -> None:
    """A machine that has never built anything has nothing to have disturbed.

    That is the ordinary state in continuous integration. The operator's machine always has a
    root, so the check that matters there still runs.
    """
    missing = tmp_path / "absent"

    assert inventory.main(["verify", "--root", str(missing)]) == 0


def test_default_root_follows_the_state_directory_variable(monkeypatch) -> None:
    monkeypatch.setenv("APEX_STATE_DIR", "/tmp/apex-example")

    assert inventory.default_root() == Path("/tmp/apex-example")


def test_classify_treats_private_key_material_as_secret() -> None:
    assert inventory.classify(Path("a/id_ed25519"), 10) is inventory.Tier.SECRET
    assert inventory.classify(Path("a/builder_ed25519"), 10) is inventory.Tier.SECRET
    assert inventory.classify(Path("a/wrong.key"), 10) is inventory.Tier.SECRET
    assert inventory.classify(Path("a/host.pem"), 10) is inventory.Tier.SECRET
    assert inventory.classify(Path("a/passphrase.txt"), 10) is inventory.Tier.SECRET
    assert inventory.classify(Path("a/id_ed25519.pub"), 10) is inventory.Tier.DIGEST


def test_a_symlink_target_is_recorded_exactly_as_stored(root: Path) -> None:
    """`Path.readlink` drops a trailing slash. An integrity manifest must not."""
    (root / "trailing").symlink_to("evidence/")

    entry = entry_for(manifest_of(root), "trailing")

    assert entry["target"] == "evidence/"
