# Fingerprint dialog regression tests

The fixture compiles GNOME 50.4's complete fingerprint dialog, manager, list row,
generated D-Bus proxies and Blueprint templates. It uses real GTK widgets and the
GLib event loop under Xvfb inside the Fedora builder. AccountsService and fprintd
are private D-Bus services implemented by the fixture. No host service or physical
sensor is involved.

Install test dependencies inside the dedicated builder, then run from the workspace:

```sh
# Inside the builder only:
sudo dnf install gtk4-devel libadwaita-devel accountsservice-devel \
    blueprint-compiler xorg-x11-server-Xvfb gcc glib2-devel libasan libubsan \
    python3-dbus python3-gobject dbus-daemon

# From the workspace, with the builder running:
just test-fingerprint-gtk RPM_BUILD_ID
```

The command verifies the source archive and binds the patch to a completed RPM build.
It compiles both the original and patched sources with AddressSanitizer and UBSan.
Each case gets a fresh private bus, service and GTK process. A failing startup cannot
count as reproduction of the original bug. Critical GLib messages, assertion failures
and sanitizer errors fail a patched case. Leak detection is disabled because this
short-lived GTK fixture retains process-global allocations; this is not a leak audit.

The cases cover:

- Protocol error, Cancel, retry and close, without a second Claim from the same owner.
- Protocol error followed by closing the dialog and opening a new one.
- Two Cancel signals while the first EnrollStop response is delayed.
- Closing the dialog with EnrollStop still pending, then draining its callbacks.
- Loss of the daemon's bus owner, replacement with a new connection and reopening.

The replacement case allows the current dialog to report ServiceUnknown while the
daemon is absent. It requires a new dialog to enroll against the replacement owner;
it does not establish seamless reconnection of the existing enrollment. Every case
checks that closing releases ownership and a new dialog can start enrollment.

Reports include source/patch hashes, library versions, individual logs and exit codes.
They live under the run's export directory, the verdict in `fingerprint.gtk.json`
beside the retrieved output. Compiler outputs are exported;
the extracted source tree stays in the VM. Source archives can contain directory
symlinks and must not be recursively copied as report contents.

On September 9, all five patched cases passed. The original source failed the four
cleanup/cancellation cases and passed the replacement/reopen case. GTK 4.22.4,
libadwaita 1.9.3, GLib 2.88.3 and AccountsService 23.13.9 matched the control image's
versions. Xvfb emitted its expected DRI3 acceleration warning; the fixture used the
Cairo renderer. Blueprint also reported the upstream GtkInfoBar deprecation.

This compiles complete components into a test executable. It does not run the
installed `gnome-control-center` executable, its surrounding system panel, GDM/PAM,
Wayland compositor or the ELAN hardware. Those checks remain separate.
