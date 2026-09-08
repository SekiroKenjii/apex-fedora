#!/usr/bin/bash
set -euo pipefail
test "$(id -u)" = 0
test "$(cat /etc/apex-builder)" = apex-isolated-builder-v1
kind=${1:?artifact kind required}
image=${2:?immutable local image ID required}
case "$image" in sha256:*) ;; *) exit 2;; esac
digest=$(jq -r .digest target-image.json)
tag="localhost/apex-payload:${digest#sha256:}"
actual=$(podman image inspect --format '{{.Id}}' "$tag")
test "sha256:${actual#sha256:}" = "$image"
test "sha256:$(skopeo inspect --raw "containers-storage:$tag" | sha256sum | cut -d ' ' -f 1)" = "$digest"
builder=$(jq -r .image_builder.reference config/sources.lock.json)
test "${builder#*@sha256:}" != "$builder"
case "$kind" in qcow2) image_type=qcow2;; installer) image_type=bootc-generic-iso;; *) exit 2;; esac
mkdir -p "output/$kind" /var/cache/apex/image-builder
podman pull "$builder"
podman run --rm "$builder" version > "output/$kind/builder-version.txt"
# The desktop payload intentionally does not carry all disk-construction tools.
podman build --pull=never --build-arg "TOOLBOX_IMAGE=$builder" \
    -f guest/artifact-builder.Containerfile -t localhost/apex-artifact-builder:trial .
buildroot_id=$(podman image inspect --format '{{.Id}}' localhost/apex-artifact-builder:trial)
buildroot="localhost/apex-artifact-builder:${buildroot_id#sha256:}"
podman tag "$buildroot_id" "$buildroot"
podman image inspect "$buildroot" > "output/$kind/buildroot-image.json"
podman run --rm --entrypoint rpm "$buildroot" -qa --qf '%{NAME}-%{EPOCHNUM}:%{VERSION}-%{RELEASE}.%{ARCH}\n' | sort > "output/$kind/buildroot-rpms.txt"
blueprint_args=()
blueprint_mount=()
payload_args=()
disk_args=(--image-size '32 GiB')
artifact_ref=$tag
if test "$kind" = installer; then
    podman build --security-opt label=disable --pull=never --build-arg "TARGET_IMAGE=$tag" \
        --build-arg "PAYLOAD_REF=$tag" -f guest/installer.Containerfile -t localhost/apex-installer:trial .
    installer_id=$(podman image inspect --format '{{.Id}}' localhost/apex-installer:trial)
    artifact_ref="localhost/apex-installer:${installer_id#sha256:}"
    podman tag "$installer_id" "$artifact_ref"
    podman image inspect "$artifact_ref" > output/installer/derived-image.json
    podman run --rm "$artifact_ref" rpm -qa --qf '%{NAME}-%{EPOCHNUM}:%{VERSION}-%{RELEASE}.%{ARCH}\n' | sort > output/installer/installer-rpms.txt
    podman run --rm "$artifact_ref" cat /usr/share/anaconda/interactive-defaults.ks > output/installer/interactive-defaults.ks
    podman run --rm "$artifact_ref" cat /usr/share/apex/installer-ui.json > output/installer/user-interface.json
    jq -n --arg digest "$digest" '{target_digest: $digest, installer_is_derived: true, automated_storage: false, selinux_required: "Enforcing", boot_test: "NOT TESTED"}' > output/installer/contract.json
    payload_args=(--bootc-installer-payload-ref "$tag")
    disk_args=()
fi
if test -f test-blueprint.toml; then
    test "$kind" = qcow2
    blueprint_args=(--blueprint /inputs/blueprint.toml)
    blueprint_mount=(-v "$PWD/test-blueprint.toml:/inputs/blueprint.toml:ro")
    jq -n '{test_only: true, differences: ["disposable user and SSH key", "sshd startup via systemd.wants"], oci_image_changed: false}' > "output/$kind/test-customizations.json"
fi
# All devices and privileged mounts here belong to the builder VM.
if test "$kind" = installer; then
    podman run --rm --privileged --security-opt label=disable \
        -v /var/lib/containers/storage:/var/lib/containers/storage \
        -v "$PWD/output/installer:/output" \
        "$builder" --output-dir /output manifest "$image_type" \
        --bootc-ref "$artifact_ref" --bootc-build-ref "$buildroot" --bootc-default-fs ext4 \
        "${payload_args[@]}" --with-sbom > output/installer/upstream-manifest.json
    python3 guest/label-installer-manifest.py output/installer/upstream-manifest.json output/installer/manifest.json output/installer/buildroot-image.json
    podman run --rm --privileged --security-opt label=disable --entrypoint /bin/bash \
        -v /etc/apex-builder:/run/apex-builder:ro \
        -v /var/lib/containers/storage:/var/lib/containers/storage \
        -v /var/cache/apex/image-builder:/var/cache/image-builder \
        -v "$PWD/output/installer:/output" -v "$PWD/guest/run-installer-osbuild.sh:/run-apex-osbuild.sh:ro" \
        "$builder" /run-apex-osbuild.sh
else
podman run --rm --privileged --security-opt label=disable \
    -v /var/lib/containers/storage:/var/lib/containers/storage \
    -v /var/cache/apex/image-builder:/var/cache/image-builder \
    -v "$PWD/output/$kind:/output" \
    "${blueprint_mount[@]}" \
    "$builder" --output-dir /output build "$image_type" \
    --bootc-ref "$artifact_ref" --bootc-build-ref "$buildroot" --bootc-default-fs ext4 "${disk_args[@]}" "${payload_args[@]}" \
    "${blueprint_args[@]}" \
    --with-manifest --with-buildlog --with-sbom --progress verbose
fi
find "output/$kind" -type f \( -name '*.qcow2' -o -name '*.iso' \) -exec sha256sum '{}' + > "output/$kind/checksums.txt"
test -s "output/$kind/checksums.txt"
