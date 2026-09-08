#!/bin/sh
set -eu
test -f /run/apex-disks-protected
/usr/libexec/apex/live-disk-guard.sh --verify
# Any disk-backed swap is a failure. zram is RAM-backed and may remain enabled.
awk 'NR > 1 && $1 !~ /^\/dev\/zram[0-9]+$/ {bad=1} END {exit bad}' /proc/swaps
test "$(getenforce)" = Enforcing
