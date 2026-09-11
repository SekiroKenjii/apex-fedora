"""The export recipe, run end to end on fakes over a small tree.

The tree is real because the walk is; nothing else touches a disk. The archive lands in
memory, the manifest lands in memory, and a refused file stops the run before either.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from apex.adapters.fakes import fake_archives, fake_files
from apex.composition import keys
from apex.composition.recipes import export_source_recipe
from apex.config import defaults
from apex.kernel import refusals, safepaths
from apex.pipeline import stages
from apex.pipeline.facts import FactMap
from apex.ports import portset


@pytest.fixture
def repository(tmp_path: Path) -> safepaths.SourceRoot:
    checkout = tmp_path / "checkout"
    (checkout / "tools").mkdir(parents=True)
    (checkout / "tools" / "run.sh").write_text("#!/bin/sh\necho hi\n")
    (checkout / "tools" / "helper.py").write_text("value = 1\n")
    (checkout / "Containerfile").write_text("FROM scratch\n")
    return safepaths.SourceRoot.adopt(checkout)


@pytest.fixture
def runtime_root(tmp_path: Path) -> safepaths.RuntimeRoot:
    base = tmp_path / "runtime"
    base.mkdir(mode=0o700)
    return safepaths.RuntimeRoot.adopt(base)


def memory_files(ports: portset.HostPorts) -> fake_files.MemoryFiles:
    assert isinstance(ports.files, fake_files.MemoryFiles)
    return ports.files


def memory_archives(ports: portset.HostPorts) -> fake_archives.MemoryArchives:
    assert isinstance(ports.archives, fake_archives.MemoryArchives)
    return ports.archives


def test_the_plan_orders_itself_from_the_facts() -> None:
    assert [str(item) for item in export_source_recipe.PLAN.order] == [
        "run.identify",
        "source.locate",
        "source.bundle",
        "source.manifest",
    ]


def test_a_clean_tree_is_bundled_and_described(
    ports: portset.HostPorts, repository: safepaths.SourceRoot, runtime_root: safepaths.RuntimeRoot
) -> None:
    outcome = export_source_recipe.export(ports, repository=repository, runtime_root=runtime_root)

    assert outcome.succeeded, outcome.detail
    bundle = outcome.facts[keys.SOURCE_BUNDLE]
    assert [entry.path for entry in bundle.files] == [
        "Containerfile",
        "tools/helper.py",
        "tools/run.sh",
    ]
    run_id = outcome.facts[keys.RUN_ID]
    assert str(bundle.archive).endswith(
        f"{defaults.EXPORT_DIRECTORY}/{run_id}/{defaults.SOURCE_ARCHIVE_NAME}"
    )


def test_the_manifest_names_every_file_and_the_archive(
    ports: portset.HostPorts, repository: safepaths.SourceRoot, runtime_root: safepaths.RuntimeRoot
) -> None:
    outcome = export_source_recipe.export(ports, repository=repository, runtime_root=runtime_root)

    run_id = outcome.facts[keys.RUN_ID]
    target = runtime_root.child(
        f"{defaults.EXPORT_DIRECTORY}/{run_id}/{defaults.SOURCE_MANIFEST_NAME}"
    )
    files = memory_files(ports)
    manifest = json.loads(files.read_bytes(target, limit=1_000_000))
    bundle = outcome.facts[keys.SOURCE_BUNDLE]
    assert manifest["archive_sha256"] == bundle.archive_digest.hex
    assert manifest["merkle_root"] == bundle.merkle_root.hex
    assert set(manifest["files"]) == {"Containerfile", "tools/helper.py", "tools/run.sh"}
    assert files.mode_of(target) == defaults.RECORD_MODE
    assert outcome.facts[keys.SOURCE_MANIFEST].hex


def test_a_file_the_repository_rules_refuse_stops_the_run_before_the_manifest(
    ports: portset.HostPorts, repository: safepaths.SourceRoot, runtime_root: safepaths.RuntimeRoot
) -> None:
    (repository.path / "tools" / "credentials.json").write_text("{}\n")

    outcome = export_source_recipe.export(ports, repository=repository, runtime_root=runtime_root)

    assert not outcome.succeeded
    assert outcome.refusal is refusals.RefusalReason.REPOSITORY_CREDENTIAL_DOCUMENT
    assert "credentials.json" in outcome.detail
    assert memory_archives(ports).written == {}
    assert memory_files(ports).writes == []


def test_every_stage_only_computes_while_the_plan_is_checked(ports: portset.HostPorts) -> None:
    context = stages.RunContext(facts=FactMap(), ports=ports.for_planning())

    for stage in export_source_recipe.PLAN.stages:
        assert stage.preflight(context) == stages.Ready()
