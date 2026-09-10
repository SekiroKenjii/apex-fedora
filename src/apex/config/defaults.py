"""The one place a number lives.

Values recorded here were measured from the working tree, not chosen. The comment beside a
value says where it was scattered before, so the duplication is visible while it is removed.
"""

from __future__ import annotations

import dataclasses

from apex.kernel import bounded, quantities, timing

# Two ports, previously one configured value and four uncoordinated literals.
BUILDER_SSH_PORT = quantities.TcpPort(22244)
GUEST_SSH_PORT = quantities.TcpPort(22245)

# Six sites in two spellings.
CAPTURE_LIMIT = bounded.Limit(262144)
# Maintained independently in the encoder and the decoder.
SERIAL_CHUNK = bounded.Limit(768)


@dataclasses.dataclass(frozen=True, slots=True)
class BuilderDefaults:
    processors: int
    memory: quantities.Mib
    reserve: quantities.Mib
    disk: quantities.Gib
    minimum_free: quantities.Gib
    ssh_port: quantities.TcpPort


BUILDER = BuilderDefaults(
    processors=4,
    memory=quantities.Mib(6144),
    reserve=quantities.Mib(1536),
    disk=quantities.Gib(160),
    minimum_free=quantities.Gib(180),
    ssh_port=BUILDER_SSH_PORT,
)


@dataclasses.dataclass(frozen=True, slots=True)
class TestMachineDefaults:
    processors: int
    memory: quantities.Mib
    ssh_port: quantities.TcpPort


TEST_MACHINE = TestMachineDefaults(
    processors=4,
    memory=quantities.Mib(4096),
    ssh_port=GUEST_SSH_PORT,
)

BOOT_READY = timing.WaitPolicy(
    deadline=timing.Deadline(timing.Elapsed(240)),
    backoff=timing.Backoff.exponential(
        first=timing.Elapsed(0.05), ceiling=timing.Elapsed(2), factor=2
    ),
    description="the guest answers on its monitor socket",
)

SHUTDOWN = timing.WaitPolicy(
    deadline=timing.Deadline(timing.Elapsed(45)),
    backoff=timing.Backoff.exponential(
        first=timing.Elapsed(0.1), ceiling=timing.Elapsed(2), factor=2
    ),
    description="the guest process exits",
)
