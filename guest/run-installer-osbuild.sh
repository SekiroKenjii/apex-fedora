#!/usr/bin/bash
set -euo pipefail
test "$(id -u)" = 0
test -f /run/.containerenv
test "$(cat /run/apex-builder)" = apex-isolated-builder-v1
test -s /output/manifest.json
# Mirror the pinned image-builder setup for direct execution of the reviewed manifest.
# This container and every device it can see are inside the dedicated Fedora VM.
cache=/var/cache/image-builder/store
mkdir -p "$cache" /run/osbuild
chcon system_u:object_r:root_t:s0 "$cache"
mount -t tmpfs tmpfs /run/osbuild
cp -p /usr/bin/osbuild /run/osbuild/osbuild
chcon system_u:object_r:install_exec_t:s0 /run/osbuild/osbuild
mount -t devtmpfs devtmpfs /dev
mount --bind /run/osbuild/osbuild /usr/bin/osbuild
osbuild --store "$cache" --output-directory /output --export bootiso --json \
    /output/manifest.json > /output/osbuild-result.json
