# Known issues

## Audio: BLOCKED

The ALC294 codec on subsystem 1043:1ab2 has required a runtime codec workaround on an
earlier installation. The operator identified its online source, which contains
several variants; the exact variant used and current boot state remain unconfirmed.
No kernel quirk or UCM patch has been justified. Collect clean cold-boot codec, mixer,
UCM and journal data before changing state. Speaker output and resume remain untested
on Apex. Do not add guessed model options or an hda-verb service.
See the [source investigation and command decoder](AUDIO.md).

## Fingerprint: BLOCKED

ELAN enrollment reports `the device is already claimed by another process`.
An observed host log shows a protocol error during identify-for-enroll before subsequent
Claim denials. This is a lead for cleanup testing, not a confirmed libfprint diagnosis.
No ownership fix has been applied. Keep password login and password administration.
Do not delete enrolled templates or restart the daemon on a timer as a product fix.
See the [ownership investigation](FINGERPRINT.md).

## Kernel and GPU: NOT TESTED

The Fedora control image does not yet contain a validated proprietary NVIDIA module set.
CachyOS builds are deliberately blocked until its kernel sources/RPMs and matching
modules have a reviewed lock. Secure Boot and module signatures require their own tests;
the build does not alter firmware settings to bypass them.

## Image integration: NOT TESTED

Greenboot counter/fallback behavior and the complete installer/update failure suite
still require image-level acceptance. A control candidate has passed ten offline boots
and a separate password-login/Wayland rendering case. Those results do not cover the
remaining failure tests. The live guard is experimental and must not be trusted on the
internal disk until virtual disk tests demonstrate its behavior.

A separately identified signed A/B fixture now passes offline forward update and
manual rollback with user data preserved. Bootc rejected wrong-key, unsigned and
untrusted-source payloads on fresh overlays. These results do not belong to the
frozen candidate. The installed static GRUB configuration did not pick up the image's
newline repair. A diagnostic repair on separate VM overlays enabled GDM-failure
tests: value 2 allowed three failed boots; one retry produced the required two.
Automatic rollback and password TTY rescue have fixture evidence, not rebuilt-image
acceptance. Production GRUB configuration migration remains blocked. Dock theme-node
and shutdown warnings also remain open. See [update testing](UPDATES.md) and
[recovery fault tests](RECOVERY-TESTS.md).

Live build `c143b7a293c540dab199b3d3fd8ab806` passed direct UEFI boot, GNOME Wayland
and visible Ptyxis with SELinux enforcing and no failed units. It corrects the earlier
Flatpak helper label loss and masks the live-only bootloader updater. Both virtual
disks and their partitions rejected actual write attempts, and complete comparisons
after poweroff found both disks unchanged. A separate pre-mount failure-latch test
stopped before mounting root or starting the desktop, also leaving both disks unchanged.
USB hotplug and a kernel-denied lock also passed in separate direct-UEFI VMs, with
whole disks unchanged. Ventoy 1.1.17 normal-mode UEFI boot also passed with visible
Wayland/Ptyxis, five internal-fixture writes denied and all three virtual disks unchanged.
Physical storage and the interval before udev finishes processing hotplug remain
untested. The guard is configured to make USB storage
read-only; unlocking only a chosen USB log partition is not implemented.
See the [live build and disk-protection findings](LIVE.md).

The Ventoy run printed `cannot load image`, `you need to load the kernel first` and
`Invalid ELF header magic` during early boot, then reached the desktop without failed
systemd units. Their cause and impact remain unconfirmed. Device-mapper's Ventoy
mappings have writable flags and refer only to the emulated USB data partition in
this fixture; the ISO is mounted read-only. No write-denial claim covers those mapped
paths. Keep these limits separate from the passing internal-disk checks. See
[Ventoy testing](VENTOY.md). Boot log review remains blocked.

The first QCOW2 boot reached GDM with SELinux enforcing and the expected digest, but
`mcelog.service` failed on the virtual AMD family 25 CPU. Its own support probe returns
1 for that CPU. The repository adds this probe as an ExecCondition so the daemon runs
only on supported processors. The corrected candidate booted with no failed units in
ten offline cycles. This does not establish physical machine-check reporting through
EDAC or rasdaemon.
See the [mcelog CPU support implementation](https://github.com/andikleen/mcelog/blob/master/mcelog.c).

The current candidate's ten-boot Q35 run recorded nine `watchdog did not stop` messages
during reboot, with an emulated ICH9 TCO device present, and ten clocksource remote-CPU
read timeouts. The guest still reached GDM with the expected digest and no failed units.
Watchdog and clocksource behavior need further investigation before recovery acceptance;
these messages have not been classified as harmless or used to draw a hardware conclusion.
See the [message paths and diagnostic procedure](BOOT-DIAGNOSTICS.md).

## Supply chain and desktop

An earlier control candidate used Graphite override fragments as complete GTK/Shell
themes, producing a transparent GTK4 window. The current signed OCI and QCOW2 retain
Adwaita-dark for GTK and compose the Shell override with Fedora's installed base
resource. GTK3 initially mixed a light background with dark controls because the named
Adwaita-dark GTK3 base was missing. The rebuilt theme RPM packages an alias to GTK3's
built-in dark resource, and the image verifier checks its resource and hash. The
current candidate passed clean VM review of GTK3, libadwaita and Shell surfaces at
1280x800. Fractional scaling, XWayland, Flatpak and the OLED panel remain untested;
that limited review is not approval of the final desktop design.

The generic installer needs an adapter for the separate tools buildroot and final
filesystem labeling. The first attempt was cancelled after its generated manifest
confirmed both omissions. Subsequent builds exposed console/SELinux entry-point
failures and an unsigned payload rejected after target formatting. The current ISO
passed clean startup, cancellation with both disks unchanged, offline installation,
ISO removal and password login. Its preflight verifies the signed compressed payload
before Anaconda starts. Six negative ISO-level payload cases also passed, with both
whole disks unchanged. Recovery fault tests remain required.
See [installer findings](INSTALLER.md) for the tested checksum.

Development file signatures exist separately from the unfinished bootc update trust
configuration. Release registry/key selection and positive/negative update tests are
still required. Exact Fedora RPM repository reconstruction is not implemented.

Lotus packaging, selective Flatpak theme permissions and optional app provisioning are
not complete. No firstboot network installer is required to reach the baseline desktop.
OLED appearance and scaling need real-panel screenshots. GNOME behavioral patches and
Apex Control remain deferred.
