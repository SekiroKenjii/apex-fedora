#!/usr/bin/bash
set -euo pipefail
test "$(id -u)" = 0
test -f /run/.containerenv
test "$(cat /run/apex-builder)" = apex-isolated-builder-v1

# Readers also need the install_t transition to see labels absent from the
# builder's policy. Otherwise getxattr can return unlabeled_t without an error.
assembler_tools=$(mktemp -d /run/apex-assembler.XXXXXX)
mount -t tmpfs -o mode=0700 tmpfs "$assembler_tools"
for program in python3 mksquashfs unsquashfs; do
    cp -L --preserve=mode "$(command -v "$program")" "$assembler_tools/$program"
    chcon system_u:object_r:install_exec_t:s0 "$assembler_tools/$program"
done
"$assembler_tools/python3" /apex-guest/prepare-live-rootfs.py
"$assembler_tools/mksquashfs" /work/live-rootfs /work/iso-root/LiveOS/squashfs.img \
    -noappend -mem 1G -processors 4 "$@"
test ! -e /work/live-label-check
"$assembler_tools/unsquashfs" -no-progress -d /work/live-label-check \
    /work/iso-root/LiveOS/squashfs.img etc/shadow usr/bin/bash usr/bin/passwd \
    usr/lib/systemd/systemd usr/libexec/flatpak-system-helper var/roothome
"$assembler_tools/python3" /apex-guest/prepare-live-rootfs.py --verify-squashfs
