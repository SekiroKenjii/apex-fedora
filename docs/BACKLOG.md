# Work queue

The current priority is a usable hardware and desktop candidate. Recovery edge-case
work is deferred while those components are implemented. Deferral does not approve
installation or change the required release checks.

## Current work

- NVIDIA: build kernel-matched modules before boot, package matching userspace and
  firmware, and provide per-application render offload with AMD driving the display.
  The [RPM build path and launcher](NVIDIA.md) are implemented. Next: resolve builder
  storage, run Mock, review vendor boot/suspend configuration and integrate a new
  image with checked initramfs and module trust. No GPU-enabled image exists yet.
- Audio and fingerprint: obtain a clean physical reproduction and fix the component
  responsible. Keep the existing source findings and fake-device results. No guessed
  codec writes or automatic claim release belong in the image.
  This is the current loop's priority. Two physical Ubuntu traces confirm missing
  cleanup and same-client Claim denials after protocol errors. A GNOME claim-state
  patch now passes twelve handler scenarios on both prepared distribution sources,
  including repeated Cancel and owner loss. An ELAN diagnostic patch passes twenty
  metadata/buffer-exclusion scenarios per source. Full GTK/driver builds, RPM/image
  integration and physical validation remain open. Resolve the builder storage gate
  before packaging; do not lower its threshold. The operator
  confirms Ubuntu speakers work after the original workaround and restart. Audio
  still needs a planned clean-baseline comparison, not another workaround. See
  [the findings](FINGERPRINT.md) and
  [the operator procedure](HARDWARE-TRACE.md).
- Desktop: finish Vietnamese input, Flatpak theme access and existing-user updates,
  then test fractional scaling and the physical OLED panel.

## Deferred until recovery acceptance

| Task | Resume when | Completion evidence |
|---|---|---|
| Replace the shared-initramfs fault fixture | Hardware candidate can be rebuilt | Fault remains bound to B across deployment reordering |
| Pre-userspace failure policy and rescue menu | Isolated fixture is available | Saved GRUB state, failure count and explicit manual power-cycle limits |
| Installed static-GRUB configuration migration | Update path is selected | Existing installation receives the tested configuration without manual repair |
| Remaining interrupted/full-disk update and required-service faults | Final candidate and isolated disks are ready | Fresh fault overlays, data preservation and working rollback |

These tasks are deferred from the current development loop, not waived for release.
The stopped initramfs fault disk must not be reused as a healthy backing. See
[the retained findings](INITRAMFS-TESTS.md).

## Follow-up diagnostics and polish

- Investigate VM clocksource/watchdog messages before relying on watchdog recovery.
  Their effect is unresolved; do not classify them as harmless.
- Revisit Ventoy startup messages and Ubuntu live shutdown behavior before physical
  rescue acceptance. Preserve the currently verified media and logs.
- Review minor GNOME/dock warnings and visual details after daily-use functions work.
- Defer scheduler/LTO tuning, extra GNOME behavior patches and Apex Control expansion
  until hardware support and the baseline desktop are stable.

USB rescue boot, backup restoration, audio/fingerprint acceptance and permission to
write the internal disk remain mandatory before replacing the working OS.
