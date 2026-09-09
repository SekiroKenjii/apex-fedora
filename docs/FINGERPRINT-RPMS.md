# Experimental fingerprint RPMs

With the dedicated Fedora builder running:

```sh
just build-fingerprint-rpms
```

This rebuilds the complete Fedora libfprint 1.94.100 and GNOME Settings 50.4 packages
through Mock, with the reviewed Apex patches. Each gets release `1.fc44.apex1`.
It does not install packages on Ubuntu, change a frozen image or select a candidate.

To test the rebuilt library, use `just test-fingerprint-rpms BUILD_ID`. This installs
only libfprint and its test package inside the builder VM, with external repositories
disabled. It runs the packaged C tests as the unprivileged builder user. Inputs,
checksums, installation output and TAP logs stay in `runtime/fingerprint-rpm-tests`.
Any missing case, skip, TODO or failing process prevents a pass. It does not start a
physical enrollment or exercise the GNOME dialog.

`config/fingerprint-rpms.lock.json` pins each official Fedora source RPM, its archive
and original spec. The build rejects unknown archive members or changed spec layouts,
adds one patch and a distinct release, and applies patches with zero fuzz. The
libfprint driver selection remains `all`, including the virtual test drivers. ELAN
metadata logging remains disabled unless explicitly enabled; this is a diagnostic
patch, not a fix for the physical protocol error.

Every run saves its source export, original and modified specs, SRPMs, binary RPMs,
Mock logs and a local RPM repository under `runtime/fingerprint-rpm-builds`. The
host verifies transferred file hashes and the patch/source identities. Retain the
Mock package list: build dependencies still come from rolling Fedora repositories.

Source trust is official HTTPS plus pinned checksums, not independently verified
source signatures. The resulting RPMs are unsigned development artifacts. They
must not be published or accepted as release packages on the strength of checksums
alone. Artifact signing and consumer rejection tests remain separate gates.

## What a successful build proves

The complete patched sources compiled and RPM packaging completed. It does not prove
that enrollment works. Neither Fedora spec runs its upstream test suite: libfprint's
spec disables it for a PyGObject compatibility issue, and GNOME Settings has no check
section. The report records these as NOT TESTED, even when the RPM build passes.

Run packaged-library and daemon tests with virtual devices in the VM, then test the
full GTK/D-Bus dialog behavior and integrate a separately identified image. Physical
enrollment and the underlying ELAN protocol failure remain release blockers. Do not
install these packages on the working Ubuntu system to bypass the live-test gates.

On September 9, the full Mock builds produced libfprint `1.94.100-1.fc44.apex1` and
GNOME Settings `50.4-1.fc44.apex1`. The installed library passed 42 state-machine and 117
fake-device C tests, with no skips. The existing eight-case fprintd suite was also
run against this patched library and fprintd `1.94.5-5.fc44`; all eight passed. These
results are separate from the upstream suites omitted by the Fedora specs and do not
validate full GTK interaction, the physical ELAN protocol or an Apex boot image.
