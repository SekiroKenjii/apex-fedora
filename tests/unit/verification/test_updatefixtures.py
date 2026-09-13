"""A completed update fixture is found by its directory or its run and read once."""

from __future__ import annotations

import dataclasses
import hashlib
import json
from pathlib import Path

import pytest
from mirroredfiles import MirroredFiles

from apex.kernel import errors, refusals, safepaths
from apex.ports import portset
from apex.verification import updatefixtures

RUN = "c" * 32
HEX = "e" * 64


def report(*, a: str = "a" * 64, b: str = "b" * 64) -> dict[str, object]:
    return {
        "status": "PASS", "id": RUN,
        "images": {
            "a": {"digest": f"sha256:{a}", "config": f"sha256:{HEX}", "identity": "x:a"},
            "b": {"digest": f"sha256:{b}", "config": f"sha256:{HEX}", "identity": "x:b"},
        },
        "files": {"a/manifest.json": HEX}, "public_key_sha256": HEX, "archive_sha256": HEX,
        "greenboot_config_sha256": "9" * 64,
    }


@pytest.fixture
def root(tmp_path: Path) -> safepaths.RuntimeRoot:
    base = tmp_path / "runtime"
    base.mkdir(mode=0o700)
    return safepaths.RuntimeRoot.adopt(base)


def placed(root: safepaths.RuntimeRoot, document: dict[str, object]) -> MirroredFiles:
    files = MirroredFiles()
    files.write_atomic(
        root.child(f"exports/{RUN}/output/results.json"), json.dumps(document).encode(),
        mode=updatefixtures.defaults.RECORD_MODE,
    )
    return files


def test_a_fixture_is_found_by_its_run_or_by_its_directory(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    files = placed(root, report())
    held = dataclasses.replace(ports, files=files)

    by_run = updatefixtures.locate(held, root, RUN)
    by_path = updatefixtures.locate(held, root, str(root.path / "exports" / RUN))

    assert by_run.directory == by_path.directory == root.child(f"exports/{RUN}")
    assert str(by_run.report.run) == RUN and by_run.preset is not None
    assert by_run.payloads.path.name == "payloads.tar"
    assert by_run.manifest("a").path.name == "manifest-a.json"


def test_a_directory_outside_the_root_and_a_missing_report_are_refused(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot, tmp_path: Path
) -> None:
    with pytest.raises(errors.Refusal) as outside:
        updatefixtures.locate(ports, root, str(tmp_path / "elsewhere"))
    with pytest.raises(errors.Refusal) as absent:
        updatefixtures.locate(ports, root, RUN)

    assert outside.value.reason is refusals.RefusalReason.PATH_OUTSIDE_RUNTIME_ROOT
    assert absent.value.reason is refusals.RefusalReason.PATH_NOT_A_REGULAR_FILE


def test_two_images_with_one_digest_are_not_a_fixture(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    files = placed(root, report(a="a" * 64, b="a" * 64))
    held = dataclasses.replace(ports, files=files)

    with pytest.raises(errors.Refusal) as raised:
        updatefixtures.locate(held, root, RUN)

    assert raised.value.reason is refusals.RefusalReason.FIXTURE_REPORT_MALFORMED


def test_the_exported_manifest_must_hash_to_the_image_s_digest(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    manifest = b'{"config": {"digest": "sha256:' + b"e" * 64 + b'"}}'
    document = report(a=hashlib.sha256(manifest).hexdigest())
    files = placed(root, document)
    files.write_atomic(
        root.child(f"exports/{RUN}/output/manifest-a.json"), manifest,
        mode=updatefixtures.defaults.RECORD_MODE,
    )
    held = dataclasses.replace(ports, files=files)
    located = updatefixtures.locate(held, root, RUN)

    updatefixtures.require_manifest(held, root, located, "a")
    (root.path / "exports" / RUN / "output" / "manifest-a.json").write_bytes(b"{}")
    with pytest.raises(errors.Refusal) as raised:
        updatefixtures.require_manifest(held, root, located, "a")

    assert raised.value.reason is refusals.RefusalReason.FIXTURE_REPORT_MALFORMED
