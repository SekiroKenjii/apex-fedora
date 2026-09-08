# Build

## Host requirements

Use Linux with KVM access, QEMU, qemu-img, OVMF, OpenSSH, curl, Python 3.11 or newer,
OpenSSL and uv. Just is optional. Firmware paths are in `config/project.json`.
The default builder has four vCPUs, 6 GiB RAM and a sparse 160 GiB disk. The launcher
also requires a 1.5 GiB host memory reserve and the configured free disk threshold.

```sh
python3 tools/apex.py hooks
python3 tools/apex.py doctor
python3 tools/apex.py sources
python3 tools/apex.py builder prepare
python3 tools/apex.py builder start
python3 tools/apex.py builder ssh
python3 tools/apex.py build fedora
```

SSH may not be ready immediately after VM startup. Check the builder serial log and
retry the SSH check. The launcher uses localhost port 22244 and a VM-specific key.
It never disables host SSH verification globally.

The default runtime directory is `$HOME/.local/share/apex-fedora/runtime`.
Set `APEX_STATE_DIR` to use another directory
outside the repository. Keep this directory private. It holds disks, keys and raw logs.
The source export uses an explicit allowlist; it does not copy the whole workspace.

## Build output

Each run has a unique directory under `runtime/exports`. A completed image run records
`result.json`, `output/image.json`, the final OCI manifest and archive, package lists,
kernel configuration, source lock, RPMs, SRPMs and Mock logs.

`image.json` distinguishes the local image configuration ID from the OCI manifest digest.
Use the manifest digest when binding test evidence. Do not replace it with an image tag.

The base image, image-builder container, source commits and downloaded archives are
pinned in `config/sources.lock.json`. Fedora RPM repositories still change over time.
The package lists document what was installed; a repository snapshot and a full RPM
checksum lock are still needed for exact reconstruction. The current pipeline does
not claim bit-for-bit reproducibility.

Source acquisition requires the reviewed `config/sources.lock.json`. A missing or
invalid lock stops the command before any download. Image references must match their
recorded digests, and every source archive must have a SHA-256 checksum and a distinct
cache filename. The command does not discover new versions from a rolling tag or branch.
Review source updates and their checksums in the lockfile before building them.

## Create artifacts without rebuilding the image

Replace the build ID below with the 32-character ID of a completed image run:

```sh
python3 tools/apex.py artifact qcow2 --build BUILD_ID
python3 tools/apex.py artifact installer --build BUILD_ID
python3 tools/apex.py artifact live --build BUILD_ID
```

For a private VM fixture, add `--test-access` to the QCOW2 command. This creates a
random-password test user and a dedicated SSH key through a private builder blueprint.
The test disk gets `systemd.wants=sshd.service`. These
changes do not alter the OCI image. Credentials stay in that run's `test-access`
directory. Do not publish or install this QCOW2 on physical hardware.

The parent OCI archive must remain in the builder VM. These commands import its exact
manifest with digest preservation and check both manifest and configuration IDs.
This matters because OCI export can change compression and the manifest digest even
when the configuration ID is unchanged. They do not select the mutable `apex:fedora`
tag. Artifact recipes are exported separately
and their source hash is recorded. A failed image run cannot be used as a parent.

QCOW2 and installer recipes use the pinned container from
[osbuild/image-builder](https://osbuild.org/docs/developer-guide/projects/image-builder/usage/).
Disk construction runs in a separate buildroot with filesystem and QEMU tools. Its
image metadata and RPM list are recorded; those packages are not added to Apex.
The installer uses `bootc-generic-iso` with a separate Anaconda image derived from the
frozen target. The recipe signs its original OCI archive and embeds the compressed
blobs in `/usr/share/apex/payload` using Skopeo's `dir:` format. The OCI digest does
not change. The Anaconda image adds installer packages and a local rescue
account, replaces its initramfs and boots a text installer. It has no automatic
partitioning or user creation directives. The operator must select storage and confirm
installation. SELinux enforcing is required, including in the installer environment.
The build records installer RPMs, image metadata, the payload contract, public key and
verification results. Its development signing key stays in the Fedora VM, outside
the build context. Anaconda's entry point verifies the manifest signature and every
blob checksum before executing upstream code. The installed Apex image keeps its
reject-all update policy; only the installer trusts this signed local payload.

Image-builder's [ISO contract](https://github.com/osbuild/image-builder/blob/main/doc/20-advanced/20-bootc/10-isos.md)
describes the required layout and notes that `anaconda-iso` is unavailable in the new
tool. The upstream example disables SELinux; Apex does not adopt that setting. ISO
labeling is added as a final `org.osbuild.selinux` stage in the generated `os-tree`
pipeline, before squashfs creation. Both upstream and modified manifests are retained.
The stage uses the installer's targeted policy. The adapter refuses disabled enforcement,
automatic kickstart arguments or an unexpected upstream labeling stage.

The adapter also selects the inspected, immutable tools buildroot for the `build`
pipeline. The pinned generic-ISO generator otherwise uses the installer as its build
environment despite `--bootc-build-ref`. The generator still receives the frozen
`--bootc-installer-payload-ref` for contract validation. The adapter removes exactly
its matching unpacked-store copy stage, since the signed compressed payload is already
inside the derived image. A missing, duplicated or changed copy stage stops the build.
Copying the unpacked image again can change layer representation and invalidate its
signature. Only the separate tools environment performs image assembly.

The reviewed manifest runs through osbuild in the pinned builder container. Its startup
script follows that builder's SELinux execution setup, inside the Fedora VM. Actual
SELinux state, manual partition selection, offline installation and installed mount
units still require VM acceptance. An installer build alone cannot pass them.
See [installer findings](INSTALLER.md) for the current console/PAM corrections and
the distinction between diagnostic startup and clean ISO acceptance.

The live recipe runs the pinned [Titanoboa](https://github.com/ublue-os/titanoboa) script
inside the builder VM. Its derived image adds live boot support and disk protection.
It must not change protected kernel, firmware, audio, fingerprint or GNOME packages.
Package comparison does not replace kernel/module file checks or an actual boot test.

The live image masks disk automount, disk swap, hibernation, automatic updates and
greenboot. Greenboot belongs to installed deployments; a live trial must not modify
boot counters on the internal disk.

## Signatures

Completed artifacts have a signed `artifacts.json` inventory and `artifacts.sig`.
The private development key stays inside the builder VM. The exported public key is
for out-of-band review, not automatic trust establishment.

For local development, `python3 tools/apex.py trust-development-key` retrieves the
public key through the builder's authenticated SSH connection and records its hash
under `runtime/trust`. It refuses an unexpected key change. This trusts the local
builder for testing; it does not select a production release key or change bootc policy.

```sh
python3 tools/apex.py verify-artifact OUTPUT_DIRECTORY --trusted-key TRUSTED_PUBLIC_KEY
python3 tools/apex.py test-artifact OUTPUT_DIRECTORY --trusted-key TRUSTED_PUBLIC_KEY
```

The trusted public key must come from a location outside the artifact directory and
must have been checked independently. A matching checksum alone establishes no trust.
Tests cover changed manifests, changed payloads, wrong keys and bundled-key rejection.
The second command exercises those cases against a completed artifact without changing
the original and writes a private proof report under `runtime/signature-tests`.

This is development signing. The target's container policy rejects all sources until
a release registry, approved signing key and scoped bootc verification policy are set.
Signed OCI update acceptance and rejection must be demonstrated inside a booted guest.
Do not weaken the policy to make an update test pass.

## Stop

```sh
python3 tools/apex.py builder stop
```

Shutdown uses QMP and gives the guest 45 seconds. If it does not shut down, the command
reports that it remains running. It does not kill an unrelated PID or reboot the host.
