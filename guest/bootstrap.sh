#!/usr/bin/bash
set -euo pipefail
test "$(id -u)" = 0
test "$(cat /etc/apex-builder 2>/dev/null)" = apex-isolated-builder-v1
case "$(systemd-detect-virt --vm)" in kvm|qemu) ;; *) exit 2;; esac
. /etc/os-release
test "$ID" = fedora
test "$VERSION_ID" = 44
dnf -y --setopt=max_parallel_downloads=4 install podman mock rpm-build createrepo_c \
    python3 nodejs git curl jq skopeo openssl tar xz unzip cpio
mkdir -p output
rpm -qa --qf '%{NAME}-%{EPOCHNUM}:%{VERSION}-%{RELEASE}.%{ARCH}\n' | sort > output/builder-rpms.txt
podman version > output/podman-version.txt
