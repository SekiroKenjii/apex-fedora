"""The recipe on real adapters bundles exactly the files the pre-restructure export bundles.

Both run over this repository, read only, and write their archive under a temporary root. The
archives themselves may differ in entry order, since the recipe sorts every path once and the
older export sorts within each declared root; the set of files and every digest must agree.
"""

from __future__ import annotations

from pathlib import Path

from apex.adapters.real import (
    real_archives,
    real_clock,
    real_digesting,
    real_downloading,
    real_files,
    real_hypervisor,
    real_ids,
    real_locking,
    real_process,
    real_qmp,
    real_signing,
)
from apex.composition import keys
from apex.composition.recipes import export_source_recipe
from apex.kernel import safepaths
from apex.ports import portset
from apexlib import pipeline as legacy

REPOSITORY = Path(__file__).resolve().parents[2]


def real_bundle(root: safepaths.RuntimeRoot) -> portset.HostPorts:
    return portset.HostPorts(
        processes=real_process.SubprocessRunner(),
        files=real_files.LocalFiles(),
        clock=real_clock.SystemClock(),
        identities=real_ids.RandomIdentities(),
        locks=real_locking.FileLocks(root),
        digests=real_digesting.CachedDigests(),
        archives=real_archives.TarArchives(),
        signing=real_signing.OpensslSigner(),
        downloads=real_downloading.CurlDownloads(),
        hypervisor=real_hypervisor.QemuHypervisor(),
        monitor=real_qmp.UnixQmp(),
    )


def test_the_recipe_and_the_older_export_agree_on_every_file(tmp_path: Path) -> None:
    base = tmp_path / "runtime"
    base.mkdir(mode=0o700)
    root = safepaths.RuntimeRoot.adopt(base)

    outcome = export_source_recipe.export(
        real_bundle(root), repository=safepaths.SourceRoot.adopt(REPOSITORY), runtime_root=root
    )
    older = legacy.export_source(tmp_path / "older.tar")

    assert outcome.succeeded, outcome.detail
    bundle = outcome.facts[keys.SOURCE_BUNDLE]
    assert {entry.path: entry.digest.hex for entry in bundle.files} == older["files"]
    assert bundle.archive.path.is_file()
    assert bundle.archive.path.stat().st_mode & 0o077 == 0
