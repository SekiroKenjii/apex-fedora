#!/usr/bin/bash
set -euo pipefail
test -r /usr/lib/os-release
findmnt --mountpoint / >/dev/null
timeout 15 bootc status --format json >/dev/null
timeout 15 busctl --system list >/dev/null
systemctl is-active --quiet gdm.service
test "$(getenforce)" = Enforcing
# Audio, fingerprint and connectivity failures are release blockers, not reboot triggers.
