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
the existing cancellation and close cleanup. The existing D-Bus owner-change path
still handles daemon disappearance. The patch is experimental and is not included
in an RPM or image yet. Physical unplug, daemon replacement, GTK integration and
downstream distribution patches need review before packaging it.

Download the exact source named in `config/gnome-fingerprint.lock.json`, then run:

```sh
just test-fingerprint-dialog /path/to/cc-fingerprint-dialog.c
```

The runner refuses a checksum mismatch, applies the patch without fuzz and compiles
three extracted GNOME handlers against test shims. The shims replace widgets and
D-Bus calls; they cannot touch a sensor. Original handlers skip Stop/Release after
the disconnected status. Patched handlers retain both calls and the cancellation
path. Retry, success, another terminal error and an unclaimed dialog are checked
separately. This does not build GNOME or exercise its full event loop, and it cannot
establish that physical enrollment succeeds.

Sources: [GNOME 50.4 dialog](https://gitlab.gnome.org/GNOME/gnome-control-center/-/blob/50.4/panels/system/users/cc-fingerprint-dialog.c),
[fprintd 1.94.5 error mapping and session handling](https://gitlab.freedesktop.org/libfprint/fprintd/-/blob/v1.94.5/src/device.c).
