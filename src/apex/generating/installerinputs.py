"""The installer image: the script that turns the target image into an Anaconda medium."""

from __future__ import annotations

from apex.model import release

SOURCE = "/apex-installer-source"
ANACONDA_VARIANT = "silverblue"
MASKED = (
    "gdm.service", "greenboot-healthcheck.service", "greenboot-reboot.service",
    "greenboot-rollback.service", "bootc-fetch-apply-updates.service",
    "bootc-fetch-apply-updates.timer",
)
UNIT_DROPINS = (
    ("installer-start.conf", "anaconda.service.d/apex-command.conf"),
    ("installer-attach.conf", "anaconda-tmux@.service.d/apex-command.conf"),
    ("installer-shell.conf", "anaconda-shell@.service.d/apex-login.conf"),
    ("installer-pre.conf", "anaconda-pre.service.d/apex-input.conf"),
)
TOOLS = ("podman", "xorriso", "mksquashfs", "implantisomd5", "grub2-mkimage", "python3")

SELECT_PAYLOAD = (
    "python3 - \"$payload\" <<'PY'\n"
    "from pathlib import Path\n"
    "import json\n"
    "import sys\n"
    "payload = sys.argv[1]\n"
    "trust = json.loads(Path('/usr/share/apex/installer-trust/payload.json').read_text())\n"
    "assert trust['identity'] == payload\n"
    "source = trust['reference']\n"
    "Path('/usr/share/anaconda/interactive-defaults.ks').write_text(\n"
    "    f'bootc --source-imgref dir:/usr/share/apex/payload --target-imgref {source}\\n')\n"
    "Path('/usr/share/apex/installer-payload.json').write_text("
    "json.dumps({'reference': payload, 'digest': trust['digest']}))\n"
    "PY\n"
)


def _record_ui(profile: release.ReleaseProfile) -> str:
    return (
        "python3 - <<'PY'\n"
        "import json\n"
        "from pathlib import Path\n"
        "from pyanaconda.core.configuration.anaconda import AnacondaConfiguration\n"
        "configuration = AnacondaConfiguration.from_defaults()\n"
        f"configuration.set_from_detected_profile('{profile.os_id}', '{ANACONDA_VARIANT}')\n"
        "configuration.set_from_files()\n"
        "assert 'UserSpoke' not in configuration.ui.hidden_spokes\n"
        "assert 'PasswordSpoke' in configuration.ui.hidden_spokes\n"
        "Path('/usr/share/apex/installer-ui.json').write_text(json.dumps({\n"
        "    'hidden_spokes': configuration.ui.hidden_spokes,\n"
        "    'user_creation': 'interactive', 'boot_test': 'NOT TESTED'}))\n"
        "PY\n"
    )


def configure(profile: release.ReleaseProfile) -> str:
    efi = f"/boot/efi/EFI/{profile.efi_vendor_directory}"
    dropins = "".join(
        f"install -Dm0644 {SOURCE}/{source} /etc/systemd/system/{target}\n"
        for source, target in UNIT_DROPINS
    )
    return (
        "#!/usr/bin/bash\n"
        "set -euo pipefail\n"
        "payload=${1:?frozen local payload reference required}\n"
        '[[ "$payload" =~ ^localhost/apex-payload:[a-f0-9]{64}$ ]]\n'
        "test -f /usr/share/apex/shell-theme-source.json\n"
        "install -d /boot/efi /usr/lib/image-builder/bootc /usr/lib/systemd/logind.conf.d\n"
        "cp -a /usr/lib/efi/*/*/EFI /boot/efi/\n"
        f"install -m 0644 {SOURCE}/installer-iso.yaml /usr/lib/image-builder/bootc/iso.yaml\n"
        "# This file selects the bundled payload but contains no storage or user directives.\n"
        + SELECT_PAYLOAD
        + f"install -Dm0644 {SOURCE}/installer-preflight.py "
        "/usr/libexec/apex/installer-preflight.py\n"
        "install -Dm0644 /usr/share/apex/installer-trust/policy.json "
        "/etc/containers/policy.json\n"
        f"python3 {SOURCE}/guard-installer-entrypoint.py\n"
        f"install -Dm0644 {SOURCE}/installer-diagnostics.py "
        "/usr/libexec/apex/installer-diagnostics.py\n"
        f"install -Dm0644 {SOURCE}/installer-ui.conf /etc/anaconda/conf.d/90-apex-ui.conf\n"
        + _record_ui(profile)
        + "# Anaconda's local installer account exists only in this derived environment.\n"
        "useradd --non-unique --uid 0 --gid 0 --no-create-home --home-dir /root \\\n"
        "    --shell /usr/libexec/anaconda/run-anaconda install\n"
        "passwd -d install\n"
        "install -m 0755 /usr/share/anaconda/list-harddrives-stub /usr/bin/list-harddrives\n"
        "mv /etc/yum.repos.d /etc/anaconda.repos.d\n"
        "# Anaconda 44.30's generator compares this literal path, not its resolved target.\n"
        "ln -sfn /lib/systemd/system/anaconda.target /etc/systemd/system/default.target\n"
        "ln -sfn /usr/lib/systemd/system/anaconda-shell@.service "
        "/etc/systemd/system/autovt@.service\n"
        f"install -m 0644 {SOURCE}/installer-logind.conf "
        "/usr/lib/systemd/logind.conf.d/anaconda-shell.conf\n"
        "for unit in anaconda.service anaconda-tmux@.service; do\n"
        f"    install -Dm0644 {SOURCE}/installer-pam.conf "
        '"/etc/systemd/system/$unit.d/apex-pam.conf"\n'
        "done\n"
        "# systemd resolves ExecStart while still in init_t. Bash is an allowed entry point;\n"
        "# PAM selects the login context before it execs the screen_exec_t-labeled tmux.\n"
        + dropins
        + f"systemctl mask {' '.join(MASKED[:3])} \\\n"
        f"    {' '.join(MASKED[3:])}\n"
        'mkdir -p "$(realpath /root)"\n'
        "mapfile -t kernels < <(find /usr/lib/modules -mindepth 1 -maxdepth 1 -type d "
        "-printf '%f\\n')\n"
        'test "${#kernels[@]}" = 1\n'
        "kernel=${kernels[0]}\n"
        "DRACUT_NO_XATTR=1 dracut --force --zstd --reproducible --no-hostonly --add anaconda \\\n"
        '    "/usr/lib/modules/$kernel/initramfs.img" "$kernel"\n'
        'test -s "/usr/lib/modules/$kernel/initramfs.img"\n'
        f"test -s {efi}/shimx64.efi\n"
        f"test -s {efi}/gcdx64.efi\n"
        "test -s /etc/selinux/targeted/contexts/files/file_contexts\n"
        "test \"$(sed -n 's/^SELINUX=//p' /etc/selinux/config)\" = enforcing\n"
        f"for tool in {' '.join(TOOLS)}; do command -v \"$tool\"; done\n"
    )
