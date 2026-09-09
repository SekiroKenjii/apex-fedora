# Initramfs failure and manual rescue

Use a fresh disposable overlay of a stopped, verified A/B disk. Keep the builder off,
check available test-VM resources, and retain private OVMF VARS, serial output and
localhost-only SSH. This test does not attach host disks or physical devices.

## Prepare the fault

The original shared-initramfs fixture exposed a test limitation: after rollback,
OSTree retargeted its bootlinks without replacing the BLS text, moving the fault onto
A. That run covers initial fault reproduction and first manual rescue only. New
injections now reject shared boot identities before writing. Prepare a separately
identified A/B fixture with distinct boot checksum paths and initramfs files before
repeating this procedure; no such replacement has been tested yet.

Verify the source QCOW2 checksum, installed GRUB configuration, signed fixture and
healthy A first. Stage signed B with `just test-update forward "$fixture" "$access"`.
Before changing its BLS entry, complete the normal finalization services through the
guest's password-protected SSH connection:

```sh
sudo systemctl stop greenboot-set-rollback-trigger.service ostree-finalize-staged.service
```

Record the units, stop ordering, journal and resulting bootc status. Both services
must finish successfully. This is deliberate test preparation: it prevents shutdown
finalization from replacing the injected BLS entry. It is not an untouched update
shutdown. Do not write GRUB counters or replace the finalization commands.

```sh
just test-initramfs-inspect "$fixture" "$access"
# Read the resulting result.json before supplying its absolute path here.
just test-initramfs-inject "$fixture" "$access" "$inspection"
```

The inspector resolves each BLS bootlink to the exact deployment and immutable A/B
marker. It requires A booted, B finalized as the pending default, two BLS entries,
SELinux enforcing, the reviewed boot component versions and the naturally armed
first-update GRUB state. It hashes kernel, initramfs, entries, GRUB and EFI files.

Injection rechecks the inspection hash, file identities and distinct boot paths.
The helper creates a separate 4 KiB truncated initramfs copy with an invalid header.
Only B's `initrd` field points to that copy. The original initramfs, kernel,
A entry, EFI files and grubenv must remain unchanged. Writes use a private guest
mount namespace; the BLS replacement is atomic and preserves its SELinux label.
The host runner retains the exact executed sources and before/after evidence.

## Observe and rescue

Record the serial offset and request one guest reboot. Require actual unpacking or
root-mount failure evidence before classifying an early-boot fault. SSH failure alone
is insufficient. Observe for a bounded period and retain the elapsed time, QMP state
and screenshot; a QMP state of `running` does not mean the guest OS is healthy.

Any QMP reset is an operator-assisted VM action, not automatic recovery. Record each
one. If necessary, enter GRUB and use `list_env` to read saved variables. An early
Escape can interrupt configuration loading; empty in-memory variables at that prompt
do not prove an empty saved environment. `normal` loads the configured menu again.
Inspect the menu and select the previously mapped A entry, without editing grubenv.

Verify A's digest after boot. Test a password TTY login and password sudo, then log out
of the TTY and repeat `just test-update check-a "$fixture" "$access"` for password GDM
login, Wayland, visible GTK rendering and preserved user data. Before any further
reboot, run `just test-initramfs-rescue "$fixture" "$access"`. This read-only guard
resolves the current bootlinks again; the pre-injection mapping is no longer enough.
If it reports BLOCKED, preserve that result and shut the guest down normally. Do not
repair the entry and report an unmodified recovery pass. Another offline boot remains
BLOCKED until a separately identified fixture keeps the fault bound to B through
deployment reordering. Retain the disk, original logs and initramfs copy, then verify
that the source backing checksum stayed unchanged.

Keep fault reproduction, automatic recovery, manual rescue and hardware acceptance
as separate results. A successful rescue must not overwrite an automatic-recovery
failure or approve the frozen candidate.

## September 9 observations

The original diagnostic used signed fixture A `bb9c21422b2b61b3bec5f67bb5ce17c6c4182d41c682704be44ac6a2e937c80e`
and B `c039d78d2df94352258852d6a5a8ceedb543725208c2116831be6bf51ecc4780`,
with greenboot 0.16.4 and bootupd 0.2.35. Installed GRUB matched the image before
injection. No GRUB repair or counter edit was made.

B failed to unpack the isolated initramfs and panicked while mounting root, before
userspace. The first observation window lasted about 124 seconds from the reboot
request; the panic log stayed unchanged through its final 83 seconds. There was no
unattended reset or recovery in that window. After an operator-assisted reset and
normal GRUB loading, B failed the same way again. A second operator-assisted reset
was used to enter the menu and select A. Longer unattended intervals were not tested.

Saved grubenv after the failures contained `boot_success=0`, the expected B digest
and `fallback=1`, but no `boot_counter`. The packaged GRUB fragment only applies its
counter logic when that variable exists. Greenboot initializes it in the failed
userspace health-check path. This explains why the GDM test does not establish a
two-attempt limit here. See the [GRUB fragment](https://github.com/fedora-iot/greenboot-rs/blob/v0.16.4/grub2/08_greenboot.cfg)
and [greenboot implementation](https://github.com/fedora-iot/greenboot-rs/blob/v0.16.4/src/main.rs).

A booted offline from the manually selected entry. Password TTY login and password
sudo passed; the terminal and authentication journal both identified tty3. GDM
password login, Wayland, visible GTK4 rendering and the user-data sentinel passed.
Greenboot detected the expected/booted digest mismatch and made A the default.
Its journal calls this a GRUB fallback; the retained reset and keyboard actions show
that entry selection required operator intervention.

The post-rescue check then found that OSTree had retargeted the existing bootlinks:
the unchanged fault-bearing BLS entry now resolved to A. The next offline boot was
blocked before reboot. This is a defect in the shared-boot-path test fixture, not
evidence that a correctly isolated image fault necessarily behaves the same way.
The new injection guard rejects that shared identity, and the read-only rescue
guard reproduced BLOCKED on the actual guest. A replacement fixture remains untested.

The guest shut down normally. Kernel, original initramfs, GRUB configuration and EFI
content hashes remained unchanged. Keep the stopped overlay as evidence; its default
entry is still faulty, so it is not a safe starting disk for another test. The clean
A/B source backing remains the starting point for future approved fixtures.

## Clocksource and watchdog observations

The guest used `kvm-clock` before and after rescue. Its iTCO watchdog was inactive in
both live observations, with `nowayout=0` and a 30-second device timeout. The systemd
manager reported runtime watchdog disabled and a ten-minute reboot watchdog. These
settings do not prove an early-panic reset path or its timing.

Two different kernel paths produced the retained messages. In upstream Linux 7.1,
[remote clocksource read timeouts](https://github.com/torvalds/linux/blob/v7.1/kernel/time/clocksource.c)
return for another check without taking the skew branch that marks a source unstable.
The [watchdog device close path](https://github.com/torvalds/linux/blob/v7.1/drivers/watchdog/watchdog_dev.c)
reports failure to stop and sends a keepalive; this includes a close without the
required magic character, as well as a failed stop operation. The message alone does
not distinguish those causes. These source references describe upstream 7.1, not a
byte-for-byte audit of Fedora's 7.1.13 package. Neither warning is dismissed as harmless;
the trigger and practical impact remain unresolved. No kernel arguments were changed.
