"""A bundle of fakes each declared a real adapter, so the minting rules can be reached.

The lie is on purpose and only for tests: the mint refuses a simulated witness, and a test
of what is recorded has to get past that refusal without a machine. A port handed in
replaces its fake, so a test can run the real Git or the real files under the same bundle.
"""

from __future__ import annotations

from typing import Any

from apex.adapters.fakes import (
    fake_archives,
    fake_clock,
    fake_digesting,
    fake_downloading,
    fake_files,
    fake_guestshell,
    fake_hypervisor,
    fake_ids,
    fake_locking,
    fake_process,
    fake_qmp,
    fake_signing,
)
from apex.kernel import claims
from apex.ports import portset


def declared_real(cls: Any) -> Any:
    return type(f"Real{cls.__name__}", (cls,), {"environment": claims.EnvironmentKind.BUILD})


def pretending_real(**held: Any) -> portset.HostPorts:
    fakes: dict[str, Any] = {
        "processes": declared_real(fake_process.ScriptedProcess)(),
        "files": declared_real(fake_files.MemoryFiles)(),
        "clock": declared_real(fake_clock.ManualClock)(),
        "identities": declared_real(fake_ids.SequenceIdentities)(),
        "locks": declared_real(fake_locking.MemoryLocks)(),
        "digests": declared_real(fake_digesting.CountingDigests)(),
        "archives": declared_real(fake_archives.MemoryArchives)(),
        "signing": declared_real(fake_signing.FakeSigner)(),
        "downloads": declared_real(fake_downloading.PinningFetcher)(),
        "hypervisor": declared_real(fake_hypervisor.FakeQemu)(),
        "monitor": declared_real(fake_qmp.ScriptedQmp)(),
        "guest": declared_real(fake_guestshell.ScriptedGuest)(),
    }
    return portset.HostPorts(**{**fakes, **held})
