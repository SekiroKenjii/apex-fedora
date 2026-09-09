# Virtual Ventoy testing

This fixture tests a file-backed USB image under QEMU UEFI. It never writes a physical
USB or passes host devices to a VM. Ubuntu remains the working host system. A passing
virtual test does not establish rescue boot on the ASUS laptop.

## Inputs

`config/ventoy-test.lock.json` pins Ventoy 1.1.17 and Ubuntu 26.04 Desktop. Ventoy's
archive checksum is checked against its release checksum file and the pinned value.
This is checksum verification over HTTPS, not a detached-signature claim for Ventoy.
See the [release](https://github.com/ventoy/Ventoy/releases/tag/v1.1.17).

Ubuntu requires its ISO, signed SHA256SUMS and a public keyring containing the signer
whose full fingerprint is pinned in the lock. The tool uses a separate GnuPG home and
requires both that signer and the exact filename, size and hash. Establish the key's
identity using Ubuntu's [verification guide](https://ubuntu.com/tutorials/how-to-verify-ubuntu).
Retain verified checksum files for the pinned release; a later point release can
change the directory's checksum list.

Use the existing Apex live output with its independently trusted artifact public key.
The tool verifies the whole signed bundle before reading `live/Apex-Live.iso`. It does
not rebuild or select another target image. Input ISOs must be regular files under
runtime storage. Copy a rescue ISO there before invoking the tool; do not pass a USB
device node, mount a host disk image or share a host directory with the builder.

## Prepare the virtual media

Start the isolated builder after the resource check, then run:

```sh
just doctor
just builder-start
just ventoy-media LIVE_OUTPUT UBUNTU_ISO TRUSTED_KEY SHA256SUMS SHA256SUMS_GPG PUBLIC_KEYRING
```

The host transfers only the fixture script, a checksum request, Ventoy and the two
ISOs over the builder's authenticated localhost SSH channel. The guest verifies the
inputs again. Inside a fresh `/var/tmp` work directory it creates a 16 GiB raw file,
allocates a loop device and checks that the loop's backing file is that exact file.
The guest refuses to format an arbitrary device supplied by a caller.

Ventoy's installer creates its default MBR layout with an exFAT data partition and
32 MiB EFI partition. The fixture reserves 2 GiB at the end without formatting it.
It copies both ISOs without modifying them, verifies their hashes on the virtual
media, unmounts, checks exFAT and converts the file to QCOW2. The output retains the
partition table, tool versions and QCOW2 checksum. Reserved space is not an implemented
persistent log or encrypted biometric partition.

The layout follows Ventoy's [disk documentation](https://www.ventoy.net/en/doc_disk_layout.html).
The pinned installer recognizes loop-device partition names in
[`get_disk_part_name`](https://github.com/ventoy/Ventoy/blob/7cbdc5cf69935bcf1f085ae67f40e70ea7e74bae/INSTALL/tool/ventoy_lib.sh).

## Boot and inspect

Stop the builder before starting the test. Use the blank 48 GiB target and partitioned
4 GiB fixture described in [Testing](TESTING.md):

```sh
just builder-stop
just test-ventoy TARGET_QCOW2 OTHER_QCOW2 VENTOY_QCOW2
```

Every run has three fresh overlays and private OVMF VARS. QEMU presents the Ventoy
overlay through emulated xHCI and USB storage, with serial `apex-ventoy-fixture` and
boot priority 1. The two other disks remain virtio fixtures. No ISO is attached as a
CD-ROM; QEMU still exposes an empty optical drive. There is no network interface,
host USB passthrough or read-only host backend masking a guest
protection failure. Resume is refused; start a fresh run for the other ISO.

Record the Ventoy menu and selected boot mode. For Apex, require a visible desktop,
SELinux enforcing, successful protection units, no failed services and no installer
autostart. Use the serial live observation and write-denial probes after reaching the
existing root session. Examine device-mapper backing devices introduced by Ventoy;
an exclusion from the disk guard does not itself prove those mappings are safe.
Internal fixtures must remain unmounted and unused as swap. Record the guest's
kernel arguments and any diagnostic changes separately.

Boot Ubuntu in a separate fresh run, verify the rescue desktop and shell, and inspect
mounts and swap without opening or installing to the internal fixtures. Ubuntu has
its own defaults; it does not inherit Apex's read-only guard. Power off each guest
normally, then compare all three complete disks:

```sh
just test-compare-disks RUN_DIRECTORY
```

Store menu and desktop screenshots, serial probe hashes, source identities and full
disk comparisons under the private run directory. Record `live.ventoy` only from
actual Apex boot and protection observations. Keep Secure Boot, physical rescue boot,
backup restoration and the physical USB's installed Ventoy version as separate checks.

## September 9 results

The 16 GiB fixture contains the unchanged Apex live ISO with SHA-256
`0c08b2d55c116b832686eccb23041e2e778bad09f09a23843145c992a0be6490` and Ubuntu ISO with
SHA-256 `487f87faaf547ea30e0aba4d5b53346292571256b25333a978db1692bcee9dd2`.
Both booted through Ventoy 1.1.17 normal mode in separate fresh UEFI guests. No kernel
arguments were edited; Ventoy added `rdinit=/vtoy/vtoy`. Reading each complete ISO
through its guest device-mapper mapping reproduced its expected hash.

Apex reached liveuser's Wayland session, rendered Ptyxis, kept SELinux enforcing and
had no failed units. Five actual writes to internal fixture nodes returned `EPERM`.
Neither internal disk was mounted or used as swap; efivarfs was read-only. Both
internal disks and the virtual USB were unchanged after guest poweroff. These results
satisfy the tested scope of `live.ventoy`.

Ventoy creates two writable-flagged linear mappings backed only by the USB data
partition in this fixture. The ISO was mounted read-only; the other mapping was not
mounted. No test attempted writes through these mappings. The first topology probe
stopped on a partition's missing `slaves` directory; its corrected version records
that absence separately from an empty list of backing devices.

Ubuntu reached a Wayland desktop and terminal, and its existing live user obtained a
root shell through sudo. Serial diagnostics were enabled after desktop startup, with
no ISO or PAM change. Internal fixtures were unmounted and unused as swap, but remained
writable under Ubuntu's own defaults. All three complete disks were unchanged after
shutdown. This establishes virtual rescue boot and shell access, not physical rescue
acceptance or a restore drill.

The first Ubuntu poweroff request was inhibited by GNOME. `systemctl poweroff -i`
began orderly shutdown; session stop waited against a 90-second timeout, and shutdown
reported a failed `/cdrom` unmount. Enter at the displayed live-medium prompt completed
poweroff. QEMU was not forcibly terminated. This is not a clean-shutdown acceptance.

Both boots printed `cannot load image` and `you need to load the kernel first` before
continuing. Apex also printed `Invalid ELF header magic`; Ubuntu printed a missing
`grub_platform` command. Their causes and impact remain unconfirmed. Retain the raw
serial logs and keep boot-log review blocked. Successful desktop startup does not
resolve these messages or establish Secure Boot and compatibility with the unverified
Ventoy version on the physical USB.
