#!/usr/bin/bash
set -euo pipefail
test "$(id -u)" = 0
test "$(cat /etc/apex-builder 2>/dev/null)" = apex-isolated-builder-v1
case "$(systemd-detect-virt --vm)" in kvm|qemu) ;; *) exit 2;; esac
profile=${1:?profile required}
kind=${2:?artifact kind required}
case "$profile" in fedora|cachyos) ;; *) exit 2;; esac
case "$kind" in image|qcow2|installer|live) ;; *) exit 2;; esac
mkdir -p output sources local-rpms
python3 guest/fetch-sources.py
bash guest/build-rpms.sh
base=$(jq -r .base.reference config/sources.lock.json)
test "${base#*@sha256:}" != "$base"
podman image exists "$base" || podman pull "$base"
# Only the build container is exempted from VM SELinux labeling for bind inputs.
# The resulting OS keeps enforcing mode and is checked again when booted.
podman build --security-opt label=disable --pull=never --build-arg "BASE_IMAGE=$base" --build-arg "KERNEL_PROFILE=$profile" \
    --tag "localhost/apex:$profile" .
podman run --rm "localhost/apex:$profile" bootc container lint --fatal-warnings
podman save --format oci-archive --output "output/apex-$profile.oci.tar" "localhost/apex:$profile"
skopeo inspect --raw "oci-archive:output/apex-$profile.oci.tar" > output/manifest.json
sha256sum "output/apex-$profile.oci.tar" > output/oci-archive.sha256
podman run --rm "localhost/apex:$profile" rpm -qa --qf '%{NAME}-%{EPOCHNUM}:%{VERSION}-%{RELEASE}.%{ARCH}\n' | sort > output/image-rpms.txt
podman run --rm "localhost/apex:$profile" sh -c 'cat /usr/lib/modules/*/config' > output/kernel-config.txt
image=$(podman image inspect --format '{{.Id}}' "localhost/apex:$profile")
image="sha256:${image#sha256:}"
digest="sha256:$(sha256sum output/manifest.json | cut -d ' ' -f 1)"
test "$(jq -r .config.digest output/manifest.json)" = "$image"
jq -n --arg image "$image" --arg digest "$digest" --arg profile "$profile" \
    '{image_id: $image, digest: $digest, profile: $profile, ready_to_install: false}' > output/image.json
cp config/sources.lock.json output/sources.lock.json
bash guest/import-payload.sh "output/apex-$profile.oci.tar" output/image.json
python3 guest/sign-artifacts.py output output/image.json
test "$kind" = image
