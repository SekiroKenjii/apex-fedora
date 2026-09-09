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
