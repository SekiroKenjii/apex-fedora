"""What a stage is allowed to do, declared so a review can see it change."""

from __future__ import annotations

import enum


class Effect(enum.StrEnum):
    READS_HOST = "reads-host"
    WRITES_RUNTIME = "writes-runtime"
    SPAWNS_VM = "spawns-vm"
    NETWORK_FETCH = "network-fetch"
    REMOTE_EXEC = "remote-exec"
    MUTATES_GUEST = "mutates-guest"
    REPLACES_HOST_FILE = "replaces-host-file"
    EMITS_EVIDENCE = "emits-evidence"
