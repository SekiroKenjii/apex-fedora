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

Use `just test-fingerprint-gtk BUILD_ID` for the [complete GTK/D-Bus fixture](FINGERPRINT-GTK.md).
It checks both original and patched sources and rejects incomplete regressions.

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

## Development image integration

After library/daemon tests and the complete GTK fixture pass:

```sh
just build-fingerprint-image PARENT_IMAGE_BUILD RPM_BUILD GTK_TEST_RUN
```

The parent must be a verified, signed Fedora control image. The build installs only
the two runtime RPMs and GNOME's filesystem subpackage, with repositories and container
network access disabled. It rejects any package addition/removal, vendor version
change or other RPM change. Kernel, firmware and module/network configuration hashes
must match the parent. The ELAN diagnostic environment remains disabled.

The image also carries the tested greenboot one-retry preset and the GRUB fragment
newline repair. The exported Containerfile records these changes. RPMs remain unsigned
development inputs verified against the completed build; the resulting OCI archive
gets a separate digest and development artifact signature. This does not configure
production update trust or select the experiment as the frozen candidate.

Create a separate test disk with `just test-disk IMAGE_BUILD_ID`. Set
`APEX_TEST_DIGEST` to the experiment's final OCI digest when running the existing
guest tests. This checks the new image without changing `candidate.json` or reusing
the control image's acceptance results. Live and recovery tests must also be rerun
for the new digest before a physical trial is proposed.

The opt-in case `test_fingerprint_image_desktop_and_recovery_configuration` also
requires `APEX_FINGERPRINT_IMAGE_TEST=1` and the normal private test disk, SSH key,
user and credential-file variables described in [Testing](TESTING.md). It checks
the three installed RPM releases, GDM password login, a rendered Wayland application,
installed GRUB/retry configuration and startup of the packaged GNOME Settings app.
Review its Settings screenshot separately. This checks recovery configuration, not
automatic fallback under injected faults or enrollment on a physical sensor.
