#!/bin/sh
set -eu
protect() {
    device=$1
    name=${device##*/}
    path=$(readlink -f "/sys/class/block/$name") || return 1
    case "$path" in
        /sys/devices/virtual/block/loop*|/sys/devices/virtual/block/dm-*|/sys/devices/virtual/block/zram*) return 0;;
        /sys/devices/*) ;;
        *) return 1;;
    esac
    [ -b "$device" ] || return 1
    [ "$(blockdev --getro "$device")" = 1 ] || blockdev --setro "$device"
    [ "$(blockdev --getro "$device")" = 1 ]
}
if [ "${1:-}" = --verify ]; then
    [ ! -e /run/apex-protection-failed ] || exit 1
    seen=0
    for entry in /sys/class/block/*; do
        [ -e "$entry" ] || continue
        seen=1
        protect "/dev/${entry##*/}" || exit 1
    done
    [ "$seen" = 1 ] || exit 1
    # Firmware variables are not a storage destination for a live trial.
    if [ -d /sys/firmware/efi/efivars ]; then
        mount -o remount,ro /sys/firmware/efi/efivars || exit 1
    fi
    touch /run/apex-disks-protected
else
    protect "${1:?block device required}" || { touch /run/apex-protection-failed; exit 1; }
fi
