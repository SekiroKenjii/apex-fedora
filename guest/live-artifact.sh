#!/usr/bin/bash
set -euo pipefail
test "$(id -u)" = 0
test "$(cat /etc/apex-builder)" = apex-isolated-builder-v1
test "${1:?}" = live
image=${2:?immutable local image ID required}
case "$image" in sha256:*) ;; *) exit 2;; esac
mkdir -p sources
python3 guest/fetch-sources.py
mkdir -p output/live titanoboa-src
tar -xf sources/titanoboa.tar.gz -C titanoboa-src --strip-components=1
python3 guest/prepare-live-builder.py titanoboa-src/build_iso.sh output/live/builder-adaptation.json
digest=$(jq -r .digest target-image.json)
tag="localhost/apex-payload:${digest#sha256:}"
actual=$(podman image inspect --format '{{.Id}}' "$tag")
test "sha256:${actual#sha256:}" = "$image"
test "sha256:$(skopeo inspect --raw "containers-storage:$tag" | sha256sum | cut -d ' ' -f 1)" = "$digest"
podman build --pull=never --build-arg "TARGET_IMAGE=$tag" -f live/Containerfile -t localhost/apex-live:trial .
podman run --rm "$image" rpm -qa --qf '%{NAME} %{EVR} %{ARCH}\n' | sort > output/live/target-rpms.txt
podman run --rm localhost/apex-live:trial rpm -qa --qf '%{NAME} %{EVR} %{ARCH}\n' | sort > output/live/live-rpms.txt
python3 guest/live-parity.py output/live/target-rpms.txt output/live/live-rpms.txt > output/live/parity.json
builder=$(jq -r .image_builder.reference config/sources.lock.json)
podman pull "$builder"
podman run --rm --privileged --security-opt label=disable --entrypoint /bin/bash \
    --mount type=image,source=localhost/apex-live:trial,destination=/rootfs,ro=true \
    -v "$PWD/titanoboa-src:/apex-titanoboa:ro" -v "$PWD/output/live:/output" \
    "$builder" /apex-titanoboa/build_iso.sh
sha256sum output/live/*.iso > output/live/checksums.txt
podman image inspect localhost/apex-live:trial > output/live/derived-image.json
