# Fingerprint investigation

The ELAN sensor remains a release blocker. No template deletion, daemon restart policy
or host authentication change has been applied.

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
fprintd journal and whether the daemon owns its D-Bus name. The September 9 Ubuntu
snapshot found fprintd inactive, no current bus owner and the ELAN device suspended.
The journal showed an earlier start and normal deactivation, without an enrollment
attempt. This does not reproduce the reported claim error. A daemon's bus name owner
is also not the client that claimed the sensor; that client still needs a timed D-Bus
trace during reproduction. The collector does not activate the daemon or read templates.

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
