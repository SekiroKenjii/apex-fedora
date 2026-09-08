#!/usr/bin/bash
set -euo pipefail
payload=${1:?frozen local payload reference required}
[[ "$payload" =~ ^localhost/apex-payload:[a-f0-9]{64}$ ]]
test -f /usr/share/apex/shell-theme-source.json
install -d /boot/efi /usr/lib/image-builder/bootc /usr/lib/systemd/logind.conf.d
cp -a /usr/lib/efi/*/*/EFI /boot/efi/
install -m 0644 /apex-installer-source/installer-iso.yaml /usr/lib/image-builder/bootc/iso.yaml
# This file selects the bundled payload but contains no storage or user directives.
python3 - "$payload" <<'PY'
from pathlib import Path
import sys
payload = sys.argv[1]
Path('/usr/share/anaconda/interactive-defaults.ks').write_text(
    f'bootc --source-imgref containers-storage:{payload} --target-imgref {payload}\n')
PY
# Anaconda's local installer account exists only in this derived environment.
useradd --non-unique --uid 0 --gid 0 --no-create-home --home-dir /root \
    --shell /usr/libexec/anaconda/run-anaconda install
passwd -d install
install -m 0755 /usr/share/anaconda/list-harddrives-stub /usr/bin/list-harddrives
mv /etc/yum.repos.d /etc/anaconda.repos.d
# Anaconda 44.30's generator compares this literal path, not its resolved target.
ln -sfn /lib/systemd/system/anaconda.target /etc/systemd/system/default.target
ln -sfn /usr/lib/systemd/system/anaconda-shell@.service /etc/systemd/system/autovt@.service
install -m 0644 /apex-installer-source/installer-logind.conf /usr/lib/systemd/logind.conf.d/anaconda-shell.conf
for unit in anaconda.service anaconda-tmux@.service; do
    install -Dm0644 /apex-installer-source/installer-pam.conf "/etc/systemd/system/$unit.d/apex-pam.conf"
done
# systemd resolves ExecStart while still in init_t. Bash is an allowed entry point;
# PAM selects the login context before it execs the screen_exec_t-labeled tmux.
install -Dm0644 /apex-installer-source/installer-start.conf /etc/systemd/system/anaconda.service.d/apex-command.conf
install -Dm0644 /apex-installer-source/installer-attach.conf /etc/systemd/system/anaconda-tmux@.service.d/apex-command.conf
install -Dm0644 /apex-installer-source/installer-shell.conf /etc/systemd/system/anaconda-shell@.service.d/apex-login.conf
install -Dm0644 /apex-installer-source/installer-pre.conf /etc/systemd/system/anaconda-pre.service.d/apex-input.conf
systemctl mask gdm.service greenboot-healthcheck.service greenboot-reboot.service \
    greenboot-rollback.service bootc-fetch-apply-updates.service bootc-fetch-apply-updates.timer
mkdir -p "$(realpath /root)"
mapfile -t kernels < <(find /usr/lib/modules -mindepth 1 -maxdepth 1 -type d -printf '%f\n')
test "${#kernels[@]}" = 1
kernel=${kernels[0]}
DRACUT_NO_XATTR=1 dracut --force --zstd --reproducible --no-hostonly --add anaconda \
    "/usr/lib/modules/$kernel/initramfs.img" "$kernel"
test -s "/usr/lib/modules/$kernel/initramfs.img"
test -s /boot/efi/EFI/fedora/shimx64.efi
test -s /boot/efi/EFI/fedora/gcdx64.efi
test -s /etc/selinux/targeted/contexts/files/file_contexts
test "$(sed -n 's/^SELINUX=//p' /etc/selinux/config)" = enforcing
for tool in podman xorriso mksquashfs implantisomd5 grub2-mkimage python3; do command -v "$tool"; done
