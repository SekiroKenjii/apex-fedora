#!/usr/bin/bash
set -euo pipefail
test "$(id -u)" = 0
test "$(cat /etc/apex-builder)" = apex-isolated-builder-v1
archive=${1:?OCI archive required}
target=${2:?image metadata required}
test -f "$archive" && test ! -L "$archive"
digest=$(jq -r .digest "$target")
image=$(jq -r .image_id "$target")
[[ "$digest" =~ ^sha256:[a-f0-9]{64}$ ]]
[[ "$image" =~ ^sha256:[a-f0-9]{64}$ ]]
tag="localhost/apex-payload:${digest#sha256:}"
# OCI export can change layer compression and therefore the manifest digest.
# Reimport that exact manifest; matching only the configuration ID is insufficient.
skopeo copy --quiet --preserve-digests "oci-archive:$archive" "containers-storage:$tag"
mkdir -p output
skopeo inspect --raw "containers-storage:$tag" > output/payload-manifest.json
test "sha256:$(sha256sum output/payload-manifest.json | cut -d ' ' -f 1)" = "$digest"
actual=$(podman image inspect --format '{{.Id}}' "$tag")
test "sha256:${actual#sha256:}" = "$image"
