"""The real host bundle, and the context a command receives."""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from pathlib import Path

from apex.adapters.real import (
    real_archives,
    real_clock,
    real_digesting,
    real_downloading,
    real_files,
    real_guestshell,
    real_hypervisor,
    real_ids,
    real_locking,
    real_process,
    real_qmp,
    real_signing,
)
from apex.config import defaults, layers, loader
from apex.kernel import errors, refusals, safepaths
from apex.ports import portset
from apex.wiring import contexts

REPOSITORY = Path(__file__).resolve().parents[3]


def bundle(root: safepaths.RuntimeRoot) -> portset.HostPorts:
    """Every port a host stage may hold, each backed by the real adapter and nothing else."""
    processes = real_process.SubprocessRunner()
    return portset.HostPorts(
        processes=processes,
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
        guest=real_guestshell.OpensshGuestShell(processes),
    )


def runtime_root(settings: loader.Settings) -> safepaths.RuntimeRoot | None:
    """The root the settings name, when it exists; an override is its own permitted base."""
    if settings.explain("runtime_root") is layers.Layer.DEFAULT:
        permitted = (Path(defaults.RUNTIME_BASE).expanduser(),)
    else:
        permitted = (settings.runtime_root,)
    try:
        return safepaths.RuntimeRoot.resolve(settings.runtime_root, permitted=permitted)
    except errors.Refusal as refusal:
        if refusal.reason is refusals.RefusalReason.PATH_NOT_A_DIRECTORY:
            return None
        raise


@dataclasses.dataclass(frozen=True, slots=True)
class Loaded:
    settings: loader.Settings
    root: safepaths.RuntimeRoot | None


def load(environment: Mapping[str, str]) -> Loaded:
    settings = loader.load(
        host_file=Path(defaults.HOST_SETTINGS_FILE).expanduser(), environment=environment
    )
    return Loaded(settings=settings, root=runtime_root(settings))


def context(environment: Mapping[str, str]) -> contexts.Context:
    loaded = load(environment)
    return contexts.Context(
        settings=loaded.settings,
        repository=safepaths.SourceRoot.adopt(REPOSITORY),
        root=loaded.root,
        environment=dict(environment),
        bundle=bundle,
    )
