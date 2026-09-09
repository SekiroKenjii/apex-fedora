# Fingerprint investigation

The ELAN sensor remains a release blocker. No template deletion, daemon restart policy
or host authentication change has been applied.

A source-level GNOME cleanup defect now has an experimental patch and a reproducer.
Operator traces also confirm the missing cleanup and same-client Claim denials on
Ubuntu. The patch does not fix the sensor's protocol error. See the
[ownership trace and patch test](HARDWARE-TRACE.md).

An observed failure reports a protocol error during identify-for-enroll, followed by
Claim denials. These are different layers: the first is a device operation failure;
the second is session ownership. Removing the ownership error alone would not establish
that enrollment works.

In fprintd 1.94.5, completed or failed enrollment runs through action-completion logic.
That logic is separate from releasing the claimed session. A client must stop/release
as required by the API; disappearance of the D-Bus owner also has its own cleanup path.
It would be unsafe to patch the daemon to release every claim on every operation error
without testing the client contract and cancellation races.

Source: [fprintd device implementation](https://gitlab.freedesktop.org/libfprint/fprintd/-/blob/v1.94.5/src/device.c)
and the [device API](https://fprint.freedesktop.org/fprintd-dev/Device.html).

Reproduction must record the owner before and after the protocol failure, the terminal
EnrollStatus event, EnrollStop/Release calls and caller disconnection. Test GNOME
Settings and the command-line client separately before involving GDM or PAM. Then use
upstream fake devices to exercise that same path and verify on the physical sensor.
Keep password login available throughout.

`just hardware-snapshot` records service state, package versions, the current boot's
fprintd journal and whether the daemon owns its D-Bus name. A daemon's bus name owner
is not the client that claimed the sensor; use a timed D-Bus trace to identify that
client. The collector does not activate the daemon or read templates.

## Physical reproduction on Ubuntu, September 9

The operator ran two captures on Ubuntu with kernel `7.0.0-31-generic`, GNOME Settings
`1:50.3-0ubuntu0.2`, fprintd `1.94.5-4` and libfprint `1:1.95.1+tod1-0ubuntu2`.
Both traces and the follow-up journal snapshot belong to the same boot. Each trace
identifies its caller as `gnome-control-center` and records a successful Claim before
enrollment starts.

| Capture window (UTC) | Enrollment evidence | Claim after the error |
|---|---|---|
| 11:52–11:53 | Protocol error during identify-for-enroll; terminal `enroll-disconnected` | Same client denied twice |
| 11:55–11:56 | Two `enroll-stage-passed` events, then a protocol error during enroll and terminal `enroll-disconnected` | Same client denied once |

Neither trace contains EnrollStop or Release between the enrollment failure and the
subsequent Claim. The denial is `net.reactivated.Fprint.Error.AlreadyInUse`, and its
caller is the same D-Bus connection whose earlier Claim succeeded. The second dialog's
wording, "another process", is misleading in these captured attempts: Settings is
claiming again while retaining its own session. The observed sequence matches the
reviewed GNOME flag-clearing branch and the extracted-handler regression.

The journal identifies protocol errors in both attempts. fprintd maps that error to
`enroll-disconnected`, which GNOME presents as "Fingerprint device disconnected".
That message does not establish a physical USB disconnection. The two successful
stages in the second attempt are progress events, not completed enrollment or proof
that the driver works reliably. They also show that failure is not confined to the
initial identify-for-enroll operation.

Capture limits matter. The first collector was interrupted after recording the client
disconnect; its overall status remains INCOMPLETE. The second finished as OBSERVED,
not PASS, and does not include client disconnect. A later snapshot found fprintd
inactive after normal deactivation. Daemon sessions changed between the attempts, so
the second successful Claim is not a same-daemon cleanup regression test. Raw traces,
process IDs and host journals remain private; no templates or fingerprint images were
collected by these tools.

No patch has been installed on Ubuntu or included in Apex. The GNOME patch now passes
twelve handler scenarios on the prepared Fedora and Ubuntu sources, including
repeated Cancel and daemon-owner loss. Full GTK/D-Bus lifecycle validation remains
open. An opt-in [ELAN metadata patch](ELAN-DIAGNOSTICS.md) passes buffer-exclusion
tests and now builds into the complete Fedora driver RPM. Do not choose a retry
quirk from these status events alone. Physical Apex enrollment and verify remain
NOT TESTED; fingerprint support still blocks release.

Both experimental RPMs have completed Mock rebuilds. The patched libfprint passed
159 installed C cases and the eight daemon cases below in the VM, with no skips.
GNOME's full GTK dialog remains untested. See [RPM build and test](FINGERPRINT-RPMS.md).

## Virtual-device regression tests

With the dedicated builder running and no other build active:

```sh
just test-fingerprint BUILD_ID
```

The runner installs the exact fprintd/libfprint RPM versions from the frozen image in
the builder VM, then starts the tests as its unprivileged user. Test code is pinned by
SHA-256 in `config/fingerprint-tests.lock.json`. Upstream creates a private system bus,
mock polkit/logind services and temporary state directories. Virtual storage uses
string identifiers; the runner imports no fingerprint images or real templates.

The six selected upstream cases cover owner disappearance, interruption during Claim,
disconnect during or after enrollment, protocol-error reporting and the enroll CLI's
error exit. Two Apex cases require a second client to acquire the device after either
explicit EnrollStop/Release or disconnect following a protocol error. They also check
that a second client cannot claim the device while the first still owns it. An error
event alone is not expected to release the claim.

Source: [fprintd 1.94.5 regression tests](https://gitlab.freedesktop.org/libfprint/fprintd/-/blob/v1.94.5/tests/fprintd.py).

Each run retains package comparisons, source hashes, logs and results under the private
runtime directory. Missing virtual-driver support or any skipped case blocks this
suite. Even a complete pass covers only the fake-device daemon contract. Physical
ELAN behavior, GNOME Settings, GDM/PAM and suspend still need their own evidence.

On September 9, all eight cases passed with Fedora `fprintd-1.94.5-5.fc44.x86_64` and
`libfprint-1.94.100-1.fc44.x86_64`, matching the frozen control image. No case skipped.
The protocol error left the claim owned until the client released it or disconnected;
both cleanup paths allowed another client to acquire the virtual device. This run
does not reproduce or resolve the physical ELAN failure.

## Driver branch for 04f3:0c6e

Both reviewed source versions select the image-based `elan` driver with
`ELAN_ALL_DEV`, not `elanmoc`. The inspected Fedora-side source is upstream 1.94.100.
The current Ubuntu source is `1:1.95.1+tod1-0ubuntu2`; its Debian patch series does
not patch `elan.c` or `elan.h`.

In `CAPTURE_READ_DATA`, the driver expects a one-byte pre-scan status of 0x55 before
requesting an image. An unexpected status reaches `FP_DEVICE_ERROR_PROTO`. The
0x0c58-specific retry branch in 1.94.100 does not apply to 0x0c6e. Do not copy that
quirk to this device without a captured status and a justified protocol comparison.
This branch is a lead, not proof of where the observed hardware failure originated.

The two source files also differ in byte-order and image-normalization handling.
Those differences occur outside the pre-scan branch and have not been tied to this
machine's error. No raw fingerprint images or USB captures have been collected.

The next diagnostic distinguishes an unexpected pre-scan status from an absent or
zero-length reply. It does not treat the 0c58 retry as a fix for this sensor. See
[the status-only diagnostic and its limits](ELAN-DIAGNOSTICS.md).

Sources: [ELAN device table](https://gitlab.freedesktop.org/libfprint/libfprint/-/blob/v1.94.100/libfprint/drivers/elan.h),
[ELAN capture state machine](https://gitlab.freedesktop.org/libfprint/libfprint/-/blob/v1.94.100/libfprint/drivers/elan.c),
[exact Ubuntu source manifest](https://archive.ubuntu.com/ubuntu/pool/main/libf/libfprint/libfprint_1.95.1+tod1-0ubuntu2.dsc).
