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
as well as the ISO. Full-image acceptance of this reader correction is still pending.

Build `2cba86b0c51a45138d4d5a35a399f043` completed these checks. Its protected RPMs
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
found both disks unchanged. This covers those fixed virtual devices only. Hotplug,
guard-failure injection and Ventoy still need separate tests.

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

## Remaining acceptance

A fresh ISO with both live-service corrections must pass direct UEFI boot, service
checks and write-denial tests in a VM, including failure injection, before a physical
trial. Keep the empty optical drive in that test. Repeat the GNOME session, rendering,
enforcing, mount/swap and whole-disk checks on that same ISO. Run Ventoy acceptance
separately.

`guest/live-probe.py` collects mounts, swap, kernel block-device state, service state
and bounded journal output through the owned VM's verified serial or SSH channel.
It refuses physical, non-root and non-live sessions. It does not rerun the guard,
unlock a disk, attempt writes or label the observations as acceptance. Keep its source
checksum and JSON with the VM's ISO checksum and whole-disk comparison.

Physical USB storage is also read-only under the guard. Unlocking only a selected USB
log partition is not implemented. The independent rescue-ISO boot, backup restore and
operator steps remain required before touching physical media or the internal disk.
