# Testing

## Tool tests

```sh
PYTHONDONTWRITEBYTECODE=1 uv run --no-project --with pytest==9.1.1 pytest
```

These tests exercise Git guards, signature verification, source exports, VM command
construction, resource refusal, evidence handling and preservation of personal CSS.
They do not establish that an operating-system image boots.

`just test-installer-trust` runs a separate eight-case signature fixture in the idle
Fedora builder. It tests both Skopeo copy and the installer's OpenImage verifier. Reports
and public keys stay under `runtime/signature-policy-tests/`; private fixture keys stay
in the VM. A passing fixture does not approve the Apex installer or update path. See
[Installer acceptance](INSTALLER.md) for the failed offline import and remaining
pre-partition trust checks.

## VM acceptance

Stop the builder first. Keep every test disk under the external runtime directory.

```sh
python3 tools/apex.py builder stop
python3 tools/apex.py test-vm /absolute/runtime/path/candidate.qcow2
```

Launching a VM does not record a PASS. Use QMP, serial output and `guest/probe.py` inside
the guest to gather observations. A running GDM unit does not prove password login,
a Wayland session or a drawn application window. Capture those separately.

Each test VM keeps its overlay, serial log, QEMU command and before/after OVMF VARS in
its own `runtime/vm-runs` directory. Starting the next test does not overwrite these.
The virtual display uses virtio-vga without host GPU forwarding or host GL access.

The opt-in integration tests in `tests/integration/test_guest.py` launch a fresh overlay
for each case. They probe critical services, ten offline boot cycles and password login
through GDM on every cycle. Each cycle must create a new Wayland session and visibly
render the GTK4 probe before rebooting. The desktop case also checks the session type and searches the QMP
screenshot for the GTK4 probe's adjacent color bars. A window-presented log alone does
not pass the rendering check. `desktop.theme-surfaces` separately requires visible
window backgrounds, controls and Shell surfaces. Color bars alone can pass even when
the surrounding theme is broken. The theme runner captures GTK3 and libadwaita controls
and a Shell surface; review its PNGs before recording visual acceptance. The runner
does not turn a screenshot capture into a visual PASS. Each boot also retains kernel
journal, warnings and GRUB/greenboot state. `boot.log-review` retains unresolved serial/journal
warnings as a release blocker. Set `APEX_TEST_DISK`, `APEX_TEST_USER`
and `APEX_TEST_SSH_KEY` to a prepared test disk and its dedicated credentials. The key
must be under runtime storage. For a QCOW2 created with `--test-access`, set
`APEX_TEST_PASSWORD_FILE` to its private `test-access/credentials.json`; the reboot
runner supplies that disposable password to guest sudo through standard input. No
passwordless policy is added to the release image. QEMU exposes SSH only on localhost
port 22245 and restricts guest
outbound traffic. Record the test account and boot-argument differences with results.
They do not count as a test of an untouched first boot or the installer user workflow.

The runner waits for the active Shell process's startup-complete journal event after
password login. It uses Escape for the Welcome dialog's Skip action, then opens and
closes Overview through QMP keyboard input. D-Bus reads confirm both transitions
before an application is launched. Startup and Overview screenshots are retained.
A session record or an application launched through SSH cannot replace this input
check. GNOME defines the startup event in
[main.js](https://github.com/GNOME/gnome-shell/blob/50.4/js/ui/main.js) and the Skip key in
[welcomeDialog.js](https://github.com/GNOME/gnome-shell/blob/50.4/js/ui/welcomeDialog.js).

The Shell theme capture also requires a visible change after its shortcut, excluding
the top bar from the comparison. This rejects an unchanged desktop or a clock tick;
the PNG still needs review to confirm that the expected menu is visible and readable.

Integration-test cleanup requests `systemctl poweroff` through the guest's private
SSH connection and waits for that exact VM to exit. The result stays blocked if the
request fails, the VM changes or shutdown exceeds 45 seconds. No forced termination
follows a timeout. The general VM stop command sends an ACPI power-key event, whose
effect depends on the desktop's power-key policy; it is not a guaranteed poweroff
while a GNOME user session is active.

```sh
PYTHONDONTWRITEBYTECODE=1 uv run --no-project --with pytest==9.1.1 pytest -m integration
```

The mandatory check IDs are in `config/checks.json`. The acceptance suite is not yet
complete. Until each runner or operator procedure supplies evidence, its result remains
NOT TESTED. Do not substitute a pytest skip for a successful acceptance result.

Each fault case starts from a new virtual disk or overlay. Required cases include:

- UEFI offline installation, user creation, ISO removal and installed boot.
- Installer cancellation with unchanged virtual disks, including a second disk and mock EFI, Windows and Linux regions.
- Installer payload rejection before storage changes, with both disks unchanged in each fresh fault VM.
- Ten boots, password login, Wayland and a rendered application window.
- Offline and interrupted firstboot. Optional app downloads must not block GDM.
- A to B updates, user data preservation, offline rollback and boot.
- Invalid signatures, untrusted sources, full disk, interrupted download and simulated power loss.
- Failed GDM, required services, corrupted initramfs and failure before userspace.
- Direct live ISO boot, Ventoy boot, no internal writable mounts and no internal swap.

`python3 tools/apex.py test-power-loss` terminates only an owned disposable test VM,
using a PID handle. It refuses the builder. This models loss of guest execution and
RAM, not loss of the physical drive's write cache. Keep that distinction in results.
The command records the injection but does not declare crash recovery successful.

Hash non-target virtual disk regions before and after installation tests. Merely seeing
the correct disk name in the installer is insufficient. Save private OVMF VARS before
and after to examine firmware changes. Never attach a host block device for these tests.

`just test-installer TARGET ISO OTHER_DISK` attaches fresh overlays for the target and
the other disk. All files and backing chains must be inside runtime storage. The other
disk has the virtual serial `apex-other-1`. No physical device is accepted. After the
guest starts, match serial and capacity; QEMU's device enumeration can put the other
disk at `/dev/vda`. Never hardcode that name as the installation target. After the
guest has shut down, `just test-compare-disks RUN_DIRECTORY` compares the complete
guest-visible contents of each overlay with its source using `qemu-img compare`.
Cancellation requires both disks to remain unchanged. A completed installation requires
the non-target disk to remain unchanged. Keep the original fixture hashes as well.

`installer.payload-rejection` is separate from detached artifact-signature and update
tests. It requires ISO-level wrong-key, missing or altered signature, changed manifest,
corrupted blob and unexpected-source cases. Inject each fault before Anaconda starts,
retain the guard's failure report and compare both disks after shutdown. Running the
guard again after a normal installer startup is only a diagnostic, not that acceptance
case. Unit tests and the builder's synthetic Skopeo fixture do not satisfy this gate.

Prepare those sources with `just installer-fixtures` while the builder is running and
idle. Formatting and loop mounts happen only inside the builder VM. The output contains
a blank 48 GiB target and a 4 GiB GPT disk with FAT32 EFI, NTFS and ext4 partitions,
each containing a sentinel file. These are formatted test filesystems, not bootable
Windows or Ubuntu installations. The report retains their partition layout, sentinel
hashes and transferred QCOW2 checksums. The host never mounts them.

`just test-resume-installed RUN_DIRECTORY` boots the same test disk and private UEFI
VARS without attaching the ISO. It preserves the previous serial log and VARS first.
This is also the path for resuming a disposable test after simulated power loss. The
tool reconstructs a restricted QEMU command; it does not execute a command read from
the saved report. Disk comparison and test resumption refuse to run while another Apex
VM is active.

## Physical acceptance

Only proceed once VM results justify a live trial. Use the same frozen digest for all
results. Keep raw logs and sensor state outside Git, with biometric state encrypted.

- Three cold boots and ten suspend/resume cycles, with battery and AC power.
- Low-volume left/right speakers, microphone, headphone jack, mute and post-resume audio. No runtime codec workaround.
- Fingerprint enroll, verify, cancel, enroll again, lock/unlock and reboot verification. Test GUI and CLI claim cleanup independently.
- NVIDIA offload, HDMI and return to runtime suspend. Do not continuously poll nvidia-smi during a sleep measurement.
- OLED at 175% and 200%, Wayland, XWayland, Flatpak, Wi-Fi, Bluetooth, webcam, touchpad and Fn keys.
- Return to Ubuntu after each trial with its filesystems and boot configuration intact.

Do not replay codec writes from an earlier workaround without decoding the verb and
checking its target. Begin diagnosis with a clean cold boot and an untouched codec dump.
Read the kernel's [HD-audio notes](https://docs.kernel.org/sound/hd-audio/notes.html).

The fingerprint regression should capture the D-Bus caller, Claim, cancellation,
protocol failure, Release and caller disconnection. Use upstream daemon/libfprint mocks
to reproduce the real failure path. A newly invented mock state machine is not proof
that the production driver releases the device. The [fprintd API](https://fprint.freedesktop.org/fprintd-dev/Device.html)
describes ownership and errors.

## Evidence and gate

Keep `candidate.json` and `evidence/` under the runtime directory. A candidate names the
OCI manifest digest. Each evidence record names a required check, the same digest,
a status and SHA-256 hashes of proof files relative to `evidence/`.

Select a signed build for testing with `select-candidate --build BUILD_ID --trusted-key KEY`.
Selecting a different digest moves the previous candidate and its evidence into
`runtime/candidate-history/`. The new candidate starts without acceptance results.
Reselecting the same digest preserves its current evidence.
Use `record CHECK STATUS --environment KIND --description DESCRIPTION --proof FILE`
through `tools/apex.py` to capture evidence. This copies proof files into private runtime
storage, adds a timestamp and archives any previous record for that check. It does not
decide whether a human observation was correct. Hardware records require `physical` as
their environment; a VM cannot attest them.

```json
{
  "check": "image.lint",
  "digest": "sha256:REPLACE_WITH_64_HEX_DIGITS",
  "status": "PASS",
  "environment": {"kind": "build", "description": "Fedora 44 isolated builder"},
  "proof": [{"path": "build-lint.txt", "sha256": "REPLACE_WITH_FILE_SHA256"}]
}
```

PASS means the stated check ran and met its criteria. FAIL means it ran and did not.
BLOCKED means a prerequisite prevents it from running. NOT TESTED means no test result
exists. A missing, changed, duplicate or stale proof prevents installation readiness.
Changing kernel, firmware, driver, GNOME, PAM or initramfs requires new evidence.

```sh
python3 tools/apex.py report
python3 tools/apex.py readiness
```

Release promotion must select the tested digest. Never rebuild after approval and
reuse its tag. The first installation still needs the separate operator decision in
[Recovery](RECOVERY.md).
