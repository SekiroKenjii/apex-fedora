#!/usr/bin/bash
set -euo pipefail
test "$(id -u)" = 0
test "$(cat /etc/apex-builder)" = apex-isolated-builder-v1
systemd-detect-virt --quiet --vm
image=${1:?frozen image ID required}
case "$image" in sha256:*) ;; *) exit 2;; esac
mkdir -p output/fingerprint fingerprint-sources/dbusmock
podman run --rm --read-only --network none --entrypoint rpm "$image" \
    -q fprintd libfprint --qf '%{NAME}-%{VERSION}-%{RELEASE}.%{ARCH}\n' \
    > output/fingerprint/target-rpms.txt
mapfile -t rpms < output/fingerprint/target-rpms.txt
test "${#rpms[@]}" = 2
dnf5 install -y "${rpms[@]}" python3-dbusmock python3-gobject python3-cairo dbus-daemon
rpm -q fprintd libfprint --qf '%{NAME}-%{VERSION}-%{RELEASE}.%{ARCH}\n' > output/fingerprint/test-rpms.txt
cmp output/fingerprint/target-rpms.txt output/fingerprint/test-rpms.txt
rpm -qa --qf '%{NAME}-%{EVR}.%{ARCH}\n' | sort > output/fingerprint/environment-rpms.txt
while read -r name checksum; do
    curl --fail --location --proto '=https' --proto-redir '=https' --max-time 90 \
        "$(jq -r .base_url config/fingerprint-tests.lock.json)$name" -o "fingerprint-sources/$name"
    test "$(sha256sum "fingerprint-sources/$name" | cut -d ' ' -f 1)" = "$checksum"
done < <(jq -r '.files | to_entries[] | "\(.key) \(.value)"' config/fingerprint-tests.lock.json)
chown builder:builder output/fingerprint
timeout --kill-after=10s 180s runuser -u builder -- env PYTHONDONTWRITEBYTECODE=1 python3 guest/test-fingerprint.py \
    fingerprint-sources output/fingerprint
