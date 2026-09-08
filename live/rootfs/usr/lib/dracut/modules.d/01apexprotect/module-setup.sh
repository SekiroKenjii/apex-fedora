#!/bin/bash
check() { return 0; }
depends() { echo systemd; }
install() {
    inst_multiple blockdev readlink mount touch
    inst_simple /usr/libexec/apex/live-disk-guard.sh /usr/libexec/apex/live-disk-guard.sh
    inst_rules "$moddir/00-apex-live-disk-guard.rules"
    inst_hook pre-mount 01 "$moddir/verify-protection.sh"
}
