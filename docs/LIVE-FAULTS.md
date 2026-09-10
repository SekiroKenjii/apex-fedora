# Live protection fixtures

These procedures use disposable QEMU guests. They do not write a physical USB, mount
host storage, change firmware or approve a laptop trial. Use the signed live ISO
identified in [Live testing](LIVE.md). Stop the builder before starting a test guest.

## USB hotplug

Start a fresh guest with the blank 48 GiB target and the 4 GiB partition fixture:

```sh
just test-live-hotplug TARGET_QCOW2 LIVE_ISO OTHER_QCOW2
```

Establish the live image's existing root session through the private serial socket.
Wait for liveuser's desktop, then collect the baseline and attach a new overlay:

```sh
just test-live-check observe
just test-hotplug-usb OTHER_QCOW2
just test-live-check usb-write-denial
just test-live-check observe
```

The host tool accepts only QCOW2 files and backing chains under runtime storage.
It uses `qemu-xhci` and `usb-storage`, with no `usb-host` device. The QMP backend is
writable so the test measures guest protection. The overlay is registered for complete
comparison before attachment, including when attachment fails. The USB has serial
`apex-usb-fixture`; the guest requires that serial on a USB descriptor ancestor, the
4 GiB size and three partitions. It checks mounts, swap and kernel read-only state,
then attempts same-byte writes on all four nodes after udev settles. Unknown identity
or state stops the test before writes. Sources: [QEMU USB emulation](https://www.qemu.org/docs/master/system/devices/usb.html)
and [QMP blockdev-add](https://www.qemu.org/docs/master/interop/qemu-qmp-ref.html#command-blockdev-add).

Power off through the guest and compare all three disks with
`just test-compare-disks RUN_DIRECTORY`. Do not resume this USB test as a normal VM;
the tool refuses because that would change the hotplug topology.

## Kernel-denied lock

Start a separate fresh two-disk live VM with `--serial-console`, without hotplug.
Add `rd.break=pre-mount rd.shell` to its GRUB kernel line. Record the edited line and
guest command line. Wait for the complete maintenance prompt and enter its shell.
The breakpoint is before the pre-mount hooks and `/sysroot` must still be unmounted.

The initramfs lacks Python. In this guest shell only, use the interpreter already
present in the read-only ISO lower filesystem:

```sh
python3() {
    PYTHONDONTWRITEBYTECODE=1 PYTHONHOME=/run/rootfsbase/usr \
    LD_LIBRARY_PATH=/run/rootfsbase/usr/lib64 \
    /run/rootfsbase/usr/bin/python3 "$@"
}
PATH=$PATH:/run/rootfsbase/usr/bin
export PATH
```

From the host, `just test-live-check lock-fault` transfers the checksum-checked fixture.
It requires QEMU, root, the live boot argument, initramfs, no mounted root and the
reviewed guard hash. It identifies the known virtual disk by serial and topology.
Udev execution is paused briefly while that disk's in-memory read-only flag is cleared.
Only the child running the unmodified guard loses `CAP_SYS_ADMIN`. Its actual
`blockdev --setro` must fail, leave the flag unset and create the failure latch.
The test restores read-only protection and resumes udev; it does not clear the latch.
No disk data is written by this fixture.

The kernel's [`blkdev_roset`](https://github.com/gregkh/linux/blob/81d3924095fd017e473332a9b6dd6dd0e3d9a59b/block/ioctl.c#L498)
returns `EACCES` when `CAP_SYS_ADMIN` is absent. The report records the child's effective
and bounding sets, the ioctl error, flag transitions and cleanup results. A different
error or failed cleanup is not a pass.

Exit the breakpoint shell. Require dracut to refuse boot and enter diagnostics with
root unmounted and GDM unavailable. Power off normally and compare both whole disks.
The fixture's first JSON result covers the denied ioctl only; it does not claim that
boot refusal or disk preservation has passed.

## September 9 results

On ISO `0c08b2d55c116b832686eccb23041e2e778bad09f09a23843145c992a0be6490`, USB hotplug
passed all four write-denial checks with `EPERM`, no mounts or swap and no failed
services. All three complete disks were unchanged after poweroff. An initial probe
stopped before writes when it tried reading an unrelated ancestor's serial attribute;
requiring USB descriptor attributes corrected that probe.

The separate lock-failure guest recorded `BLKROSET: Permission denied`, missing
`CAP_SYS_ADMIN`, flag transitions `1 -> 0 -> 0 -> 1`, and a retained failure latch.
Resuming boot entered diagnostics before root mount or GDM. Both disks were unchanged.
Together with the earlier normal-boot and failure-latch cases, these satisfy the
direct-UEFI VM scope of `live.disk-protection`. Ventoy, physical storage and the interval
before udev finishes processing hotplug are not covered by these results.
