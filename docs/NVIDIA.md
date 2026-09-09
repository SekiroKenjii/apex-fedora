# NVIDIA packaging and render offload

The Fedora control image remains unchanged. The driver path currently produces an
RPM build set, not a boot-tested NVIDIA image. Do not install these RPMs on the host.

## Locked build inputs

`config/nvidia.lock.json` pins NVIDIA 610.57.04, its open-module source commit,
the vendor signing key and nine userspace/firmware RPMs. The first target is Fedora
kernel `7.1.13-200.fc44.x86_64`, built with GCC `16.2.1-2.fc44`. A different kernel
or compiler requires a reviewed lock change. Missing packages stop the build;
there is no fallback to the builder VM's running kernel.

NVIDIA requires matching open modules, userspace and GSP firmware. RTX 3050 Laptop
GPU is listed in the supported-device table. These upstream statements establish
the choice of driver, not acceptance on this laptop. See the pinned
[module source](https://github.com/NVIDIA/open-gpu-kernel-modules/tree/e4a5faa2567f28c8eabe0ebb6422b6d0abcf37eb)
and the [Fedora 44 driver repository](https://developer.download.nvidia.com/compute/cuda/repos/fedora44/x86_64/).

## Build the RPM set

Start the dedicated Fedora builder only after its resource checks pass. Then run:

```sh
just build-nvidia CONTROL_BUILD_ID
```

The command requires a completed Fedora image build. It imports that build's frozen
OCI payload, reads the target kernel and compiler from the image, then builds
`kmod-apex-nvidia-open` with Mock. Privileged operations stay inside the builder VM.
The driver build uses two make jobs and requires at least 24 GiB free inside the VM,
in addition to the host's existing builder-start threshold.

The recipe includes `nvidia`, `nvidia_modeset`, `nvidia_drm` and `nvidia_uvm`.
It excludes the RDMA and vGPU modules. It does not bypass the compiler check,
load a module, run DKMS/akmods, choose the display GPU or change power management.
Module metadata checks run both before packaging and against the RPM staging tree.

Vendor RPMs are downloaded over HTTPS, checked against their SHA-256 pins and
verified in a temporary RPM key database containing only the pinned NVIDIA key.
Digest-only success is rejected: a valid signature is required. The key fingerprint
and each package's name, epoch, version, release and architecture must match the lock.
The key pin comes from NVIDIA's HTTPS repository; it is separate from Apex artifact
signing and Secure Boot trust.

The exported result contains the SRPM, binary RPMs, local repository metadata,
Mock logs, lock, package dependencies, scriptlets and file inventories. Every
transferred artifact is checksum-checked. A successful `rpm-build` result leaves
image integration, initramfs, Secure Boot and hardware checks `NOT TESTED`; it does
not select a new candidate or replace the existing OCI image.

## Per-application offload

The next build of `apex-config` includes:

```sh
apex-gpu status
apex-gpu run --gpu nvidia -- PROGRAM ARGUMENTS
```

`status` reads PCI sysfs attributes. It does not open a GPU device, call `nvidia-smi`
or claim that an `active`/`suspended` reading proves a power-management result.
Unreadable attributes are reported as `null`, not inferred to be healthy.

`run` requires exactly one NVIDIA display device bound to the `nvidia` driver and
a non-root caller. It passes the PRIME/GLX/Vulkan offload variables only to the
requested process, preserving argument boundaries. It does not change GNOME's
environment, Xorg configuration or the display GPU. The variables follow NVIDIA's
[PRIME render-offload documentation](https://download.nvidia.com/XFree86/Linux-x86_64/610.57.04/README/primerenderoffload.html).
Flatpak runtime matching and GNOME's discrete-GPU launch menu still need integration
tests; the launcher does not supply either of them.

## Next image-integration step

After the RPM build passes, inspect its retained vendor configuration and scriptlets
before adding the packages to a new image. In particular, the vendor packages ship
modprobe, udev, dracut and suspend configuration. Their presence is not approval to
enable a persistence daemon, alter suspend behavior or force GPU power parameters.

The image step must resolve all dependencies, retain SELinux enforcing, run depmod
for the target kernel and regenerate its bootc initramfs. Inspect the installed and
live initramfs for AMD, NVIDIA, GSP firmware, storage and recovery modules. Keep
userspace, kernel and firmware identical between the two artifacts. Live package
parity already rejects changes to the custom kmod and NVIDIA userspace packages.

Module signing and the intended Secure Boot trust path remain unresolved. Do not
disable firmware validation to make an unsigned experimental module load. RPM
signatures, OCI signatures and kernel module signatures cover different boundaries.

Then run VM boot/regression tests and physical offload, HDMI, suspend and idle-power
tests on the same candidate digest. Confirm the application's renderer, close it,
and observe dGPU sleep without repeatedly querying NVIDIA management tools. A VM
without hardware passthrough cannot pass these hardware cases.

## Current verification

Source archive bytes, the public key and all nine RPM checksum pins have been checked
against downloaded upstream metadata. Unit tests cover lock drift, checksum errors,
signature-result rejection, mismatched compiler/module metadata, host refusal and
the launcher. These tests use simulated RPM command results; actual RPM signature
and Mock build checks have not run yet.

The builder storage blocker was resolved by an approved cleanup, without lowering
the host or guest thresholds. Fingerprint RPM work used the recovered space first;
the NVIDIA Mock build still needs to run. Audio and fingerprint acceptance remain
blocked.
