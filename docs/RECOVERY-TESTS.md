# Recovery fault fixtures

These tests use signed A/B images in disposable QEMU overlays. They do not approve
the frozen candidate or a physical installation. Keep the builder stopped, use
private OVMF VARS and localhost SSH, and start each fault case from a fresh copy of
the known-good A/B snapshot. Never attach a physical disk.

## Installed GRUB configuration

Bootupd 0.2.35 embeds the image's configuration fragments when installing GRUB.
Updating the image does not refresh that installed file. On this fixture,
`bootupctl migrate-static-grub-config` returns `Already using a static GRUB config`
and leaves the old configuration unchanged. Its migration path handles older
OSTree-generated configurations, not replacement of existing static fragments.
The backend install operation also installs bootloader components and rewrites its
state. It is not used as a configuration-refresh shortcut here.

The test-only `repair-grub` operation fixes the single joined command/comment line
after checking its SHA-256 and the repaired image fragment. It saves the original,
checks GRUB syntax, preserves the SELinux label, replaces the file atomically and
flushes the filesystem in a private guest mount namespace. It verifies that grubenv
did not change. Evidence also captures EFI files, BLS entries and bootupd state.
This is a diagnostic repair, not an upstream-supported production migration.
The latter remains BLOCKED. Do not install this helper as a release boot service.

Sources: [bootupd 0.2.35 migration](https://github.com/coreos/bootupd/blob/v0.2.35/src/bootupd.rs#L725),
[static configuration assembly](https://github.com/coreos/bootupd/blob/v0.2.35/src/grubconfigs.rs).

## Count failed boots, not the configuration value

Greenboot 0.16.4 initializes its counter after the first failed health check.
`GREENBOOT_MAX_BOOT_ATTEMPTS=2` therefore permits three failed userspace boots:
the first failure, then two retries. The original fixture reproduced this and failed
the required two-boot limit. Greenboot eventually rolled back successfully, but that
does not turn the failed limit test into a pass.

The source preset now uses `GREENBOOT_MAX_BOOT_ATTEMPTS=1`: one retry after the
first failure. Recheck this behavior whenever greenboot changes. It does not prove
a two-attempt bound for hangs before userspace or for a health-check process that
cannot run. Source: [greenboot's failure path](https://github.com/fedora-iot/greenboot-rs/blob/v0.16.4/src/main.rs#L387).

The fault helper adds an `ExecStartPre` that exits 42 only when the booted digest
is B. GDM itself fails, and the image's unchanged Apex health check rejects it.
On A, that helper succeeds. This matters because shared mutable configuration must
not break the recovery deployment too. The observer records boot IDs, image digests,
GDM state and GRUB variables before and after health checks. It never changes the
counter or requests rollback.

## Run and evaluate

Start a fresh installed test overlay with `test-vm --guest-ssh --serial-console`.
Use the completed signed fixture directory and its private test-access directory
from [update testing](UPDATES.md). The operations below act only on that running VM:

```sh
just test-recovery inspect "$fixture" "$access"
just test-recovery native-migration "$fixture" "$access"
just test-recovery repair-grub "$fixture" "$access"
# Omit retry-config when reproducing the original three-failure result.
just test-recovery retry-config "$fixture" "$access"
just test-recovery arm-gdm "$fixture" "$access"
just test-update forward "$fixture" "$access"
just test-recovery reboot "$fixture" "$access"
```

Only the initial guest reboot is requested by the runner. Observe the subsequent
boots through QMP/serial and collect once automatic recovery has settled:

```sh
just test-recovery collect "$fixture" "$access"
just test-update check-a "$fixture" "$access"
```

`tests/integration/test_recovery_result.py` reads the retained collection named by
`APEX_RECOVERY_REPORT` and the fixture's `output/results.json` named by
`APEX_RECOVERY_FIXTURE`. It requires actual GDM exit-42 events, the production health
check failure, distinct boot IDs, a persistent counter sequence, greenboot's rollback
event and healthy A. Three failures yield FAIL. Missing observations block evaluation.
Keep the JUnit output and original failure report.

The `check-a` operation separately checks password login, Wayland, a visibly rendered
GTK4 window and the user-data sentinel. Test TTY independently: switch to a login TTY,
inspect the password prompt, authenticate normally and run a command through password
sudo. Keep prompt/result screenshots and authentication records private. SSH success
or an existing root rescue shell does not satisfy password TTY acceptance.

## September 9 results and limits

The original configuration failed the two-boot limit with three distinct failed B
boots. A fresh overlay with one retry returned to A after exactly two failed B boots.
Both runs used the exact newline diagnostic repair; neither rebuilt the images.
The two-retry run also passed password TTY login and password sudo after fallback.
The one-retry run passed password GDM login, Wayland and visible GTK4 rendering after
fallback and after another offline reboot. The user sentinel, kernel and installed
initramfs hashes stayed unchanged. Both VMs shut down normally. Their original A/B
backing snapshot was preserved.

Production migration, rebuilt-image acceptance, kernel/initramfs failures, required
service timeouts and physical recovery remain unfinished. These results do not cover
Ubuntu restoration, audio, fingerprint or the laptop's internal-disk boot path.
