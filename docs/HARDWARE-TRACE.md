# Audio baseline and fingerprint ownership trace

These procedures diagnose the current OS. They do not install a driver, change PAM,
write a codec register or approve Apex hardware support. Run the fingerprint capture
yourself; it needs permission to monitor the system bus.

## Audio baseline

Run `just hardware-snapshot` before a workaround, mixer change or test playback.
The collector saves codec dumps, mixer controls, output routing, HDA pin configuration
and relevant kernel logs in the private runtime directory. It does not play or record
sound. Empty `init_verbs` or `driver_pin_configs` files do not prove that no kernel
fixup ran; they are not a trace of every internal codec operation.

Record whether you powered the machine off completely or used Restart, whether
Windows ran before this boot, and whether any audio workaround ran afterward. Kernel
uptime cannot distinguish a cold boot from a restart. State whether ordinary audio
is audible through the built-in speakers, headphones or neither. A visible sink,
unmuted controls and a valid route do not establish speaker output.

Keep the baseline before deliberately reproducing silence. Do not reboot the working
machine or change persistent services just to collect this information. A clean
cold-boot trial requires an agreed time and operator action.

## Capture fingerprint ownership

Run from the repository in a terminal:

```sh
bash tools/observe-fingerprint.sh
```

Enter your sudo password in that terminal. Only the fixed, 90-second `busctl` monitor
runs as root. The collector runs as your desktop user. It does not request a Claim,
activate fprintd, start an enrollment or change daemon configuration.

While capture runs:

1. Open GNOME Settings and its fingerprint enrollment dialog.
2. Reproduce the reported error, then cancel and close Settings. In this first
   capture, do not delete fingerprints or finish an enrollment. If it only waits
   for a finger, cancel and report that instead.
3. Wait for capture to finish and keep the printed output path. Then run
   `just hardware-snapshot` to retain the matching fprintd journal.

The collector stores only allowed method names, correlated replies, status codes,
relevant client disconnects, timestamps and process identity when available. It drops
method arguments, usernames, error-message bodies and unrelated bus events before
writing files. It never reads templates, USB payloads or fingerprint images. Output
files have mode 0600 under a private directory outside Git.

`OBSERVED` means metadata was captured, not a test pass. Initial ownership stays unknown
unless a successful Claim is observed. Client disconnect alone does not prove cleanup;
a later successful Claim provides evidence of reacquisition. Missing replies, malformed
input or no events produce an incomplete capture. Do not change the system-bus policy
to bypass a permission error, restart daemons or delete biometric data for this test.

## GNOME claim-state patch

The reviewed upstream GNOME 50.3 and 50.4 dialog files are byte-identical. Their
`enroll-disconnected` branch clears both the claimed and enrolling flags. But fprintd
1.94.5 uses this status for protocol errors as well as removal and overheating. A
protocol error does not itself release the claimed session. Losing those flags makes
the dialog skip its normal EnrollStop/Release cleanup; a later Claim can fail even
when the same Settings process still owns the device.

`rpms/patches/gnome-fingerprint-retain-claim.patch` preserves those flags, retaining
the existing cancellation and close cleanup. It also ignores repeated Cancel while
EnrollStop is pending. Without this guard, a second Cancel cancels the Stop request;
its cancellation callback returns without clearing the stopping/enrolling flags.
This sequence was reproduced with the extracted handlers and real GCancellable
objects. The patch is experimental. Its complete GNOME Settings RPM now builds in
Mock, but it is not included in an Apex image yet.

Download the exact source named in `config/gnome-fingerprint.lock.json`, then run:

```sh
just test-fingerprint-dialog /path/to/cc-fingerprint-dialog.c
```

The runner refuses a checksum mismatch, applies the patch without fuzz and compiles
six extracted GNOME handlers against test shims. It uses the source's real state enum
and GLib cancellation objects; widgets, D-Bus replies and dialog ownership are modeled.
The twelve scenarios cover the disconnected status, retry/success/other error,
unclaimed close, owner loss/presence, Stop success/error, repeated Cancel and closing
while Stop is pending. Callback ordering is controlled by the harness.

Both distribution sources pass the patched expectations and reproduce the original
cleanup and repeated-Cancel defects. A daemon-loss notification clears the claimed
flag and requests reacquisition without sending stale close cleanup in the harness.
That is not a live daemon-replacement test. Full GTK object lifetime, real asynchronous
D-Bus races, physical unplug and image integration remain untested. No test here opens
the sensor or establishes successful enrollment.

The runner needs a C compiler, pkg-config and GLib/GIO development headers. Full RPM
builds still belong in the isolated Fedora builder. Do not install development or
patched driver packages on the working OS just to run these tests.

## Distribution source audit

The Fedora `gnome-control-center-50.4-1.fc44` source RPM contains the upstream archive
and a spec with no patches. Its dialog matches the previously reviewed source.
Ubuntu `1:50.3-0ubuntu0.2` has forty patches in its series. One changes the fingerprint
dialog: `system-users-Keep-fingerprint-add-print-popover-visible-w.patch`. It changes
popover positioning and scrolling, without altering the cleanup handlers.

The Ubuntu dialog was prepared by applying that patch to the matching source archive.
Both its C and Blueprint hunks applied without fuzz. The Apex patch then applied with
the expected line offsets and passed the same handler tests. Prepared-file and package
hashes are in `config/gnome-fingerprint.lock.json`. The checksum audit binds the review
to these bytes; source signatures have not been independently validated. Release
provenance must record that limitation instead of treating the hash check as signature
verification.

Source packages: [Fedora GNOME source RPM](https://kojipkgs.fedoraproject.org/packages/gnome-control-center/50.4/1.fc44/src/gnome-control-center-50.4-1.fc44.src.rpm),
[Ubuntu source manifest](https://archive.ubuntu.com/ubuntu/pool/main/g/gnome-control-center/gnome-control-center_50.3-0ubuntu0.2.dsc).

Sources: [GNOME 50.4 dialog](https://gitlab.gnome.org/GNOME/gnome-control-center/-/blob/50.4/panels/system/users/cc-fingerprint-dialog.c),
[fprintd 1.94.5 error mapping and session handling](https://gitlab.freedesktop.org/libfprint/fprintd/-/blob/v1.94.5/src/device.c).
