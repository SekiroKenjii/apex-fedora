"""The image build: its Containerfile and the script that configures the image inside it."""

from __future__ import annotations

from apex.config import defaults
from apex.model import builds, release

DEFAULT_PROFILE = builds.Profile.FEDORA
MOUNTS = (
    ("local-rpms", "/tmp/apex-rpms"),
    ("guest", "/tmp/apex-guest"),
    ("config", "/tmp/apex-build-config"),
)
CONFIGURE = "image-configure.sh"
GREENBOOT = ("greenboot", "0.16.4", "0")
PACKAGES = (
    "papirus-icon-theme",
    "papirus-icon-theme-dark",
    "gnome-shell-extension-user-theme",
    "gnome-shell-extension-dash-to-dock",
    "fprintd",
    "fprintd-pam",
    "ptyxis",
    "firefox",
    "alsa-utils",
    "libva-utils",
)
MASKED = ("bootc-fetch-apply-updates.timer", "bootc-fetch-apply-updates.service")
USER_UNIT = "apex-desktop-defaults.service"
ICON_THEME = "Papirus-Dark"
CACHYOS_REFUSAL = (
    "CachyOS profile blocked: a reviewed kernel RPM and matching NVIDIA package lock are required"
)


def containerfile() -> str:
    mounts = " \\\n".join(
        f"    --mount=type=bind,source={source},target={target},ro" for source, target in MOUNTS
    )
    return (
        "ARG BASE_IMAGE\n"
        "FROM ${BASE_IMAGE}\n"
        f"ARG KERNEL_PROFILE={DEFAULT_PROFILE}\n"
        "RUN" + mounts[3:] + " \\\n"
        f'    bash {MOUNTS[1][1]}/{CONFIGURE} "${{KERNEL_PROFILE}}" && '
        "bootc container lint --fatal-warnings\n"
    )


def _pinned(profile: release.ReleaseProfile) -> str:
    name, version, build = GREENBOOT
    return f"{name}-{version}-{profile.dist_tag.applied(build)}"


def configure(profile: release.ReleaseProfile) -> str:
    theme = defaults.SHELL_THEME_NAME
    guest = MOUNTS[1][1]
    packages = " ".join(PACKAGES[:2]) + " \\\n    " + " ".join(PACKAGES[2:4]) + " \\\n    "
    packages += " ".join(PACKAGES[4:]) + f" {_pinned(profile)}"
    return (
        "#!/usr/bin/bash\n"
        "set -euo pipefail\n"
        "profile=${1:?}\n"
        f"install -Dm0644 {guest}/verify-image.py /usr/libexec/apex/verify-image.py\n"
        f"install -Dm0644 {MOUNTS[2][1]}/policy.json /etc/containers/policy.json\n"
        ". /etc/os-release\n"
        f'test "$ID" = {profile.os_id}\n'
        f'test "$VERSION_ID" = {profile.os_release_version_id}\n'
        'case "$profile" in\n'
        f"    {builds.Profile.FEDORA}) ;;\n"
        f"    {builds.Profile.CACHYOS})\n"
        f"        echo '{CACHYOS_REFUSAL}' >&2\n"
        "        exit 2;;\n"
        "    *) exit 2;;\n"
        "esac\n"
        f"dnf5 -y install {MOUNTS[0][1]}/*.rpm {packages}\n"
        "dnf5 check\n"
        f"python3 {guest}/compose-shell-theme.py "
        "/usr/share/gnome-shell/gnome-shell-theme.gresource \\\n"
        f"    /usr/share/themes/{theme}/gnome-shell/apex-overrides.css \\\n"
        f"    /usr/share/themes/{theme}/gnome-shell > {defaults.SHELL_THEME_SOURCE}\n"
        "grep -qxF 'system-db:local' /etc/dconf/profile/user || "
        "printf '\\nsystem-db:local\\n' >> /etc/dconf/profile/user\n"
        "dconf update\n"
        f"python3 {guest}/fix-schema-overrides.py\n"
        "glib-compile-schemas --strict /usr/share/glib-2.0/schemas\n"
        f"gtk-update-icon-cache -f /usr/share/icons/{ICON_THEME}\n"
        "fc-cache -f\n"
        f"systemctl mask {' '.join(MASKED)}\n"
        "# Authentication keeps the Fedora password policy until sensor tests pass.\n"
        f"systemctl enable {USER_UNIT} --global\n"
        "install -m 0644 /usr/share/apex/greenboot.conf /etc/greenboot/greenboot.conf\n"
        "chmod 0755 /usr/lib/greenboot/check/required.d/20-apex-system.sh\n"
        "systemctl enable greenboot-healthcheck.service\n"
        "test -f /usr/lib/bootupd/grub2-static/configs.d/08_greenboot.cfg\n"
        f"python3 {guest}/fix-grub-fragment.py "
        "/usr/lib/bootupd/grub2-static/configs.d/08_greenboot.cfg \\\n"
        "    > /usr/share/apex/greenboot-fragment.json\n"
        "mkdir -m 0700 /run/apex-verify-user\n"
        "XDG_RUNTIME_DIR=/run/apex-verify-user systemd-analyze --user verify "
        f"/usr/lib/systemd/user/{USER_UNIT}\n"
        "mapfile -t kernels < <(find /usr/lib/modules -mindepth 1 -maxdepth 1 -type d "
        "-printf '%f\\n')\n"
        'test "${#kernels[@]}" = 1\n'
        "kver=${kernels[0]}\n"
        'test -f "/usr/lib/modules/$kver/vmlinuz"\n'
        "# The control profile does not change kernel, modules or early-boot configuration.\n"
        "# Preserve Fedora's initramfs; regeneration belongs to a reviewed kernel/driver build.\n"
        'test -s "/usr/lib/modules/$kver/initramfs.img"\n'
        'sha256sum "/usr/lib/modules/$kver/initramfs.img" '
        "> /usr/share/apex/installed-initramfs.sha256\n"
        'lsinitrd "/usr/lib/modules/$kver/initramfs.img" > /usr/share/apex/initramfs-contents.txt\n'
        "python3 /usr/libexec/apex/verify-image.py > /usr/share/apex/static-checks.json\n"
        'test "$(getenforce)" != Disabled || test -f /.dockerenv || test -f /run/.containerenv\n'
        "dnf5 clean all\n"
        f"python3 {guest}/clean-image.py\n"
    )
