# Live image testing

Apex live is derived from the frozen target OCI image. Build it with
`just artifact live BUILD_ID` in the isolated Fedora builder, then stop that VM before
starting a test VM. No command in this procedure writes USB media or installs on the host.

## Filesystem assembly

The pinned Titanoboa adapter copies the deployed tree into a separate VM scratch mount,
excluding OSTree object storage. It separates hardlinks, preserves numeric owners and
modes, and labels the copy with the target's compiled SELinux policy. The labeler,
metadata reader, squashfs writer and verification extractor run in `install_t`; the
builder stays enforcing. A failed labeling pass or nonempty relabel dry run stops
assembly. After compression, critical paths are extracted and checked for unchanged
labels, ownership, modes and content hashes. Artifact signatures cover these reports
as well as the ISO. The rebuilt ISO passed these checks and direct VM boot; see the
current result below. Ventoy and physical acceptance remain untested.

Earlier build `2cba86b0c51a45138d4d5a35a399f043` completed the initial scratch-label
checks, before the raw-reader and post-extraction correction. Its protected RPMs
matched the target; a separate comparison found 4,850 identical regular kernel/module
files, excluding the intentionally different initramfs. These comparisons do not cover
the missing NVIDIA stack, full firmware contents or hardware behavior.

That ISO has SHA-256
`caabf2e2db411ebafa0e8949f16e80b6d62e239c3dd141cb105aeac9a9f1b601`.
Its signatures and negative artifact-signature tests passed, but its normal UEFI boot
failed before the desktop. It is not approved for a physical live trial.

## Early disk protection

The initramfs udev rule processes block-device add/change events. The guard checks the
kernel's sysfs `ro` attribute, sets writable disks and partitions read-only through
`BLKROSET`, then reads the state back. Missing or unexpected state, a failed ioctl or an
ineffective ioctl blocks boot. A previous udev failure remains latched. The pre-mount
check covers discovered devices and remounts efivarfs read-only before desktop startup.

Reading `ro` does not require opening media. This matters for an empty optical drive:
the UEFI test VM exposed `sr1` with sysfs `ro=1`, but `blockdev --getro` failed to open it
with `No medium found`. That failure caused the tested ISO to abort even though both
data disks and their partitions had been made read-only. The diagnostic boot retained
the guard and added only `rd.break=pre-mount rd.shell rd.udev.log_level=debug`.
Complete comparisons after shutdown found both virtual disks unchanged.

The source uses sysfs for the state check. Linux exposes the disk flag through
[`disk_ro_show`](https://github.com/gregkh/linux/blob/81d3924095fd017e473332a9b6dd6dd0e3d9a59b/block/genhd.c),
and effective partition read-only state through
[`part_ro_show`](https://github.com/gregkh/linux/blob/81d3924095fd017e473332a9b6dd6dd0e3d9a59b/block/partitions/core.c).
The ioctl implementation is in
[`block/ioctl.c`](https://github.com/gregkh/linux/blob/81d3924095fd017e473332a9b6dd6dd0e3d9a59b/block/ioctl.c).
Unit tests run the shell control flow against file fixtures, including empty media,
failed locks, missing state, media-change events and firmware-remount failure. They
do not establish kernel enforcement or live boot acceptance.

## Direct boot and label-reader regression

Build `9c724ad63dc74f1ea540b6c3ceaf27ab` includes the sysfs guard correction. Its ISO
has SHA-256 `a01038ba7962480cd3810770047465db952616d2311da542da9a2b28f5c1bcf1`.
All 12 artifact files verified against the independently trusted development key, and
negative artifact-signature checks passed. Direct UEFI boot with no added arguments
reached a liveuser Wayland session and a visible Ptyxis window. The guard completed,
SELinux remained enforcing, efivarfs was read-only and neither virtio disk was mounted
or used for swap. Only zram swap was present.

Opening the protected virtual devices for writing succeeded, so an open-only test
would not establish write protection. Actual `pwrite` attempts on both disks and all
three partitions returned `EPERM`. Each attempted to write back the same 512 bytes
already at offset zero. The guest was then shut down normally; complete comparisons
found both disks unchanged. This covers those fixed virtual devices only. The newer
ISO has a separate failure-latch result below; hotplug and Ventoy remain untested.

Two service failures keep this ISO rejected. `bootloader-update.service` attempted
`bootupctl update` and failed to find a block device at `/boot` or `/sysroot`. Its
upstream live check does not cover this overlay layout. The live recipe now masks it;
the installed-image recipe is unchanged. `flatpak-system-helper.service` failed at
EXEC with permission denied. Its executable was mode 0755 but carried `unlabeled_t`
in both the squashfs lower tree and the live root. The loaded policy accepted the
intended `flatpak_helper_exec_t` context.

A builder diagnostic read the same scratch file in two SELinux domains: `spc_t`
returned `unlabeled_t`, while `install_t` returned the intended raw label. A one-file
squashfs round trip reproduced the loss with the ordinary packer and preserved the
label, mode and content hash with the `install_t` packer. Linux returns the raw context
for a caller with the required MAC administration permission; otherwise it can return
the current policy's mapped context without reporting an error. See
[`selinux_inode_getsecurity`](https://github.com/gregkh/linux/blob/81d3924095fd017e473332a9b6dd6dd0e3d9a59b/security/selinux/hooks.c#L3400).

The source correction puts the readers and packer in `install_t`, adds the Flatpak
helper to required probes and rejects changed metadata after extraction. The small
round-trip result does not validate a complete rebuilt ISO or Flatpak service startup.

## Current direct-boot result

Build `c143b7a293c540dab199b3d3fd8ab806` contains both corrections and retains target
OCI digest `sha256:2daf0bc614838352a65af743e2e0efb658e040169dd95e25520eb1334f42c912`.
Its ISO SHA-256 is
`0c08b2d55c116b832686eccb23041e2e778bad09f09a23843145c992a0be6490`.
All 13 artifact files verified against the independently trusted development key.
Changed manifest, changed payload, wrong key and bundled-key trust tests rejected
the invalid input. Protected RPM parity and extracted critical-file metadata passed.

Normal direct UEFI boot in a fresh two-disk VM with no NIC reached liveuser Wayland
and rendered Ptyxis. The empty optical drive remained present. SELinux was enforcing,
Flatpak helper was active with `flatpak_helper_exec_t` in both filesystem layers,
the live bootloader updater was masked and no systemd units had failed. Firmware
variables were read-only. Neither virtio disk was mounted; no swap was active at the
final observation. All five disk/partition nodes rejected actual same-byte writes
with `EPERM`. After normal poweroff, complete comparisons found both disks unchanged.
`live.direct` is PASS for this ISO. This is not permission to boot it on the laptop.

Two probe issues were corrected during this run. Fedora's `swapon` lacks `--json`,
so the read-only collector now uses its supported raw table format alongside
`/proc/swaps`. Virtio exposes its serial on the block node, not `device/serial`.
The first write test stopped during identity validation before any write attempt;
the corrected test passed. Original failed captures remain with the private evidence.

## Pre-mount failure latch

A second fresh VM booted the same ISO with `rd.break=pre-mount rd.shell`. The packaged
dracut script enters this breakpoint before sourcing pre-mount hooks. With root still
unmounted, invoking the guard on a nonexistent fixture node returned 1 and created
the failure latch. Resuming boot produced `Apex disk protection failed` and
`Refusing to continue`, then entered a diagnostic shell.

The guest remained in initramfs, `/sysroot` was not mounted and GDM was unavailable
and inactive. All five virtio nodes stayed read-only and no swap was active. Normal
poweroff and complete disk comparisons confirmed no changes. This single failure
case passed; it does not exercise a failed `BLKROSET`, hotplug or Ventoy boot.

## Remaining acceptance and probe use

Test hotplug and failed locking in separate disposable guests, then run Ventoy
acceptance. Keep `live.disk-protection` as NOT TESTED until its remaining cases have
evidence. Repeat affected tests when the ISO changes; retain the empty optical drive.

`guest/live-probe.py` collects mounts, swap, kernel block-device state, service state
and bounded journal output through the owned VM's verified serial or SSH channel.
It refuses physical, non-root and non-live sessions. It does not rerun the guard,
unlock a disk, attempt writes or label the observations as acceptance. Keep its source
checksum and JSON with the VM's ISO checksum and whole-disk comparison.

`guest/live-write-denial.py` is a separate, mutating test for the disposable QEMU
fixtures. Transfer it through the same verified serial channel only after reviewing
the read-only observations. It requires the blank 48 GiB virtio disk and the 4 GiB disk
with serial `apex-other-1` and three partitions. All five nodes must be read-only,
unmounted and unused by swap or device-mapper. The test checks device identities,
then attempts to write back the original first 512 bytes. Only `EPERM` or `EROFS`
counts as write rejection; an I/O error is blocked, and a successful write fails.
It stops at the first unsuccessful case. Shut down the VM and compare both complete
disk images afterward. Its result does not cover hotplug, guard failure or Ventoy.

The guard is configured to make USB storage read-only. Unlocking only a selected USB
log partition is not implemented. The independent rescue-ISO boot, backup restore and
operator steps remain required before touching physical media or the internal disk.
