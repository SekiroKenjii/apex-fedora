#!/usr/bin/bash
set -euo pipefail
dnf5 install -y dracut-live livesys-scripts grub2-efi-x64-cdboot
chmod 0755 /usr/lib/dracut/modules.d/01apexprotect/*.sh /usr/libexec/apex/live-*.sh
systemctl mask udisks2.service swap.target systemd-hibernate.service systemd-hybrid-sleep.service
systemctl mask bootc-fetch-apply-updates.timer bootc-fetch-apply-updates.service
systemctl mask bootloader-update.service
systemctl mask greenboot-healthcheck.service greenboot-set-rollback-trigger.service
install -m 0644 /usr/lib/dracut/modules.d/01apexprotect/00-apex-live-disk-guard.rules /usr/lib/udev/rules.d/00-apex-live-disk-guard.rules
dconf update
systemctl enable livesys.service livesys-late.service apex-live-protection.service
systemctl set-default graphical.target
mapfile -t kernels < <(find /usr/lib/modules -mindepth 1 -maxdepth 1 -type d -printf '%f\n')
test "${#kernels[@]}" = 1
kver=${kernels[0]}
install -d -m 0700 "$(realpath /root)"
DRACUT_NO_XATTR=1 dracut --force --zstd --reproducible --no-hostonly --kver "$kver" \
    --omit ostree --add 'dmsquash-live dmsquash-live-autooverlay apexprotect' \
    "/usr/lib/modules/$kver/initramfs.img"
lsinitrd "/usr/lib/modules/$kver/initramfs.img" > /usr/share/apex/live-initramfs.txt
grep -q apex-live-disk-guard /usr/share/apex/live-initramfs.txt
mkdir -p /boot/efi
cp -a /usr/lib/efi/*/*/EFI /boot/efi/
cp /boot/efi/EFI/fedora/grubx64.efi /boot/efi/EFI/BOOT/fbx64.efi
dnf5 clean all
