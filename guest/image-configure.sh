#!/usr/bin/bash
set -euo pipefail
profile=${1:?}
install -Dm0644 /tmp/apex-guest/verify-image.py /usr/libexec/apex/verify-image.py
install -Dm0644 /tmp/apex-build-config/policy.json /etc/containers/policy.json
. /etc/os-release
test "$ID" = fedora
test "$VERSION_ID" = 44
case "$profile" in
    fedora) ;;
    cachyos)
        echo 'CachyOS profile blocked: a reviewed kernel RPM and matching NVIDIA package lock are required' >&2
        exit 2;;
    *) exit 2;;
esac
dnf5 -y install /tmp/apex-rpms/*.rpm papirus-icon-theme papirus-icon-theme-dark \
    gnome-shell-extension-user-theme gnome-shell-extension-dash-to-dock \
    fprintd fprintd-pam ptyxis firefox alsa-utils libva-utils greenboot-0.16.4-0.fc44
dnf5 check
python3 /tmp/apex-guest/compose-shell-theme.py /usr/share/gnome-shell/gnome-shell-theme.gresource \
    /usr/share/themes/Shadcn-Graphite/gnome-shell/apex-overrides.css \
    /usr/share/themes/Shadcn-Graphite/gnome-shell > /usr/share/apex/shell-theme-source.json
grep -qxF 'system-db:local' /etc/dconf/profile/user || printf '\nsystem-db:local\n' >> /etc/dconf/profile/user
dconf update
python3 /tmp/apex-guest/fix-schema-overrides.py
glib-compile-schemas --strict /usr/share/glib-2.0/schemas
gtk-update-icon-cache -f /usr/share/icons/Papirus-Dark
fc-cache -f
systemctl mask bootc-fetch-apply-updates.timer bootc-fetch-apply-updates.service
# Authentication keeps the Fedora password policy until sensor tests pass.
systemctl enable apex-desktop-defaults.service --global
install -m 0644 /usr/share/apex/greenboot.conf /etc/greenboot/greenboot.conf
chmod 0755 /usr/lib/greenboot/check/required.d/20-apex-system.sh
systemctl enable greenboot-healthcheck.service
test -f /usr/lib/bootupd/grub2-static/configs.d/08_greenboot.cfg
mkdir -m 0700 /run/apex-verify-user
XDG_RUNTIME_DIR=/run/apex-verify-user systemd-analyze --user verify /usr/lib/systemd/user/apex-desktop-defaults.service
mapfile -t kernels < <(find /usr/lib/modules -mindepth 1 -maxdepth 1 -type d -printf '%f\n')
test "${#kernels[@]}" = 1
kver=${kernels[0]}
test -f "/usr/lib/modules/$kver/vmlinuz"
# The control profile does not change kernel, modules or early-boot configuration.
# Preserve Fedora's initramfs; regeneration belongs to a reviewed kernel/driver build.
test -s "/usr/lib/modules/$kver/initramfs.img"
sha256sum "/usr/lib/modules/$kver/initramfs.img" > /usr/share/apex/installed-initramfs.sha256
lsinitrd "/usr/lib/modules/$kver/initramfs.img" > /usr/share/apex/initramfs-contents.txt
python3 /usr/libexec/apex/verify-image.py > /usr/share/apex/static-checks.json
test "$(getenforce)" != Disabled || test -f /.dockerenv || test -f /run/.containerenv
dnf5 clean all
python3 /tmp/apex-guest/clean-image.py
