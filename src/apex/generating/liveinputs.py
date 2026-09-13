"""The live medium: its Containerfile, the script that configures it, and the squashfs step."""

from __future__ import annotations

from apex.model import release

PACKAGES = ("dracut-live", "livesys-scripts", "grub2-efi-x64-cdboot")
MASKED = (
    ("udisks2.service", "swap.target", "systemd-hibernate.service", "systemd-hybrid-sleep.service"),
    ("bootc-fetch-apply-updates.timer", "bootc-fetch-apply-updates.service"),
    ("bootloader-update.service",),
    ("greenboot-healthcheck.service", "greenboot-set-rollback-trigger.service"),
)
ENABLED = ("livesys.service", "livesys-late.service", "apex-live-protection.service")
DRACUT_MODULES = "dmsquash-live dmsquash-live-autooverlay apexprotect"
PROTECT_MODULE = "/usr/lib/dracut/modules.d/01apexprotect"
GUARD_RULES = "00-apex-live-disk-guard.rules"
ASSEMBLER_PROGRAMS = ("python3", "mksquashfs", "unsquashfs")
SQUASHFS_OPTIONS = "-noappend -mem 1G -processors 4"
LABEL_CHECK_PATHS = (
    "etc/shadow",
    "usr/bin/bash",
    "usr/bin/passwd",
    "usr/lib/systemd/systemd",
    "usr/libexec/flatpak-system-helper",
    "var/roothome",
)


def containerfile() -> str:
    return (
        "ARG TARGET_IMAGE\n"
        "FROM ${TARGET_IMAGE}\n"
        "COPY live/rootfs /\n"
        "COPY live/configure.sh /tmp/apex-live-configure.sh\n"
        "RUN bash /tmp/apex-live-configure.sh && rm /tmp/apex-live-configure.sh\n"
    )


def configure(profile: release.ReleaseProfile) -> str:
    efi = f"/boot/efi/EFI/{profile.efi_vendor_directory}"
    masks = "".join(f"systemctl mask {' '.join(units)}\n" for units in MASKED)
    return (
        "#!/usr/bin/bash\n"
        "set -euo pipefail\n"
        f"dnf5 install -y {' '.join(PACKAGES)}\n"
        f"chmod 0755 {PROTECT_MODULE}/*.sh /usr/libexec/apex/live-*.sh\n"
        + masks
        + f"install -m 0644 {PROTECT_MODULE}/{GUARD_RULES} /usr/lib/udev/rules.d/{GUARD_RULES}\n"
        "dconf update\n"
        f"systemctl enable {' '.join(ENABLED)}\n"
        "systemctl set-default graphical.target\n"
        "mapfile -t kernels < <(find /usr/lib/modules -mindepth 1 -maxdepth 1 -type d "
        "-printf '%f\\n')\n"
        'test "${#kernels[@]}" = 1\n'
        "kver=${kernels[0]}\n"
        'install -d -m 0700 "$(realpath /root)"\n'
        'DRACUT_NO_XATTR=1 dracut --force --zstd --reproducible --no-hostonly --kver "$kver" \\\n'
        f"    --omit ostree --add '{DRACUT_MODULES}' \\\n"
        '    "/usr/lib/modules/$kver/initramfs.img"\n'
        'lsinitrd "/usr/lib/modules/$kver/initramfs.img" > /usr/share/apex/live-initramfs.txt\n'
        "grep -q apex-live-disk-guard /usr/share/apex/live-initramfs.txt\n"
        "mkdir -p /boot/efi\n"
        "cp -a /usr/lib/efi/*/*/EFI /boot/efi/\n"
        f"cp {efi}/grubx64.efi /boot/efi/EFI/BOOT/fbx64.efi\n"
        "dnf5 clean all\n"
    )


def assemble() -> str:
    tools = "$assembler_tools"
    return (
        "#!/usr/bin/bash\n"
        "set -euo pipefail\n"
        'test "$(id -u)" = 0\n'
        "test -f /run/.containerenv\n"
        'test "$(cat /run/apex-builder)" = apex-isolated-builder-v1\n'
        "\n"
        "# Readers also need the install_t transition to see labels absent from the\n"
        "# builder's policy. Otherwise getxattr can return unlabeled_t without an error.\n"
        "assembler_tools=$(mktemp -d /run/apex-assembler.XXXXXX)\n"
        f'mount -t tmpfs -o mode=0700 tmpfs "{tools}"\n'
        f"for program in {' '.join(ASSEMBLER_PROGRAMS)}; do\n"
        f'    cp -L --preserve=mode "$(command -v "$program")" "{tools}/$program"\n'
        f'    chcon system_u:object_r:install_exec_t:s0 "{tools}/$program"\n'
        "done\n"
        f'"{tools}/python3" /apex-guest/prepare-live-rootfs.py\n'
        f'"{tools}/mksquashfs" /work/live-rootfs /work/iso-root/LiveOS/squashfs.img \\\n'
        f'    {SQUASHFS_OPTIONS} "$@"\n'
        "test ! -e /work/live-label-check\n"
        f'"{tools}/unsquashfs" -no-progress -d /work/live-label-check \\\n'
        f"    /work/iso-root/LiveOS/squashfs.img {' '.join(LABEL_CHECK_PATHS[:3])} \\\n"
        f"    {' '.join(LABEL_CHECK_PATHS[3:])}\n"
        f'"{tools}/python3" /apex-guest/prepare-live-rootfs.py --verify-squashfs\n'
    )
