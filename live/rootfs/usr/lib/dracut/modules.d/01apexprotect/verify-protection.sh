#!/bin/sh
# dracut supplies die. No root filesystem is mounted if protection failed.
/usr/libexec/apex/live-disk-guard.sh --verify || die "Apex disk protection failed; do not continue to the desktop"
