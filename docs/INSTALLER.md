# Installer acceptance

The installer is a derivative of the frozen Apex OCI image. It is separate from the
GNOME live trial. Building and signing an ISO does not approve it for a physical disk.

## Signed-payload ISO test result

The ISO with SHA-256
`ee8eeed043d1a64486abdec7e0098497fa161e44300ddd81489f41fce9b902ac`
booted through UEFI without a NIC and kept SELinux enforcing. Before Anaconda started,
the guard verified the signature and all 259 payload blobs, totaling 2,828,532,327 bytes.
That check took 7.594 seconds in the cancellation VM. USB timing remains untested.

The cancellation case selected only the 48 GiB virtual target and a Standard Partition
layout, then quit before starting installation. QMP observed Anaconda's guest reset;
the runner stopped that VM before its next boot. Complete disk comparisons found both
the target and the separate EFI/NTFS/ext4 fixture unchanged. The serial log capture was
complete.

A fresh VM completed offline installation with no NIC. Anaconda created the selected
48 GiB target's EFI, `/boot` and ext4 root partitions, deployed the bundled image and
created the manually entered password-protected administrator. After ISO removal,
the same virtual disk and private UEFI state booted to GDM. That password opened a
Wayland session, Ptyxis rendered and accepted input, and password-based sudo worked.
SELinux remained enforcing. Full comparison found the separate disk unchanged.

`bootc status` reported the original OCI digest
`sha256:2daf0bc614838352a65af743e2e0efb658e040169dd95e25520eb1334f42c912`.
There is no rollback deployment on this first installation. The recorded image
reference is a development-only localhost reference; it is not an approved update
source. The target's reject-all update policy remains in place.

Negative pre-partition cases, recovery fault tests and hardware checks remain required.
No physical installation is approved.

## Previous unsigned-payload ISO result

The rebuilt ISO starts the text installer automatically with SELinux enforcing. A clean
cancellation test selected only the 48 GiB virtual target, returned to the summary and
quit without starting installation. Complete disk comparisons found both the target and
the separate EFI/NTFS/ext4 fixture unchanged. Serial log collection also passed without
a NIC or manual service changes.

Offline installation failed. Anaconda accepted a password-protected administrator
account and the selected disk layout, then formatted the target. During payload import,
`bootc` rejected the bundled image under the inherited container signature policy. The
non-target virtual disk remained unchanged. No installed boot or account login from
this ISO has passed; an unchanged second disk during a failed install does not complete
the successful-installation test.

These results apply to the ISO with SHA-256
`8b6ece4f83e6be11d3ffb3d037e5f24674e00bb56667c57961d0f5dd6e820ba2`,
built from OCI digest
`sha256:2daf0bc614838352a65af743e2e0efb658e040169dd95e25520eb1334f42c912`.
The ISO is not ready for a physical installation.

## Console fixes verified in the rebuilt ISO

The first completed generic ISO booted through UEFI into Fedora userspace with SELinux
enforcing, but its text installer did not start automatically. Three paths need care:

- Anaconda 44.30's generator compares the default-target symlink with the literal
  `/lib/systemd/system/anaconda.target`. A symlink to `/usr/lib/...` does not match,
  even though it resolves to the same file on this filesystem.
- The upstream rescue unit runs Bash directly from agetty. The observed shell remained
  in `getty_t` and could not inspect service state. Passing through `login` selected
  the normal PAM/SELinux login context without disabling enforcement.
- systemd rejected direct execution of the `screen_exec_t`-labeled tmux from `init_t`.
  Adding PAM alone did not fix its executable lookup. A transient test using an
  allowed Bash entry point, PAM login and then `exec tmux` succeeded.

The recipe now uses the expected symlink, PAM for the server/console units and Bash
entry points for tmux. The rescue getty uses login. The pre-install logging unit uses
null input after its original console-attached process received SIGHUP. No permissive
domain, broad allow module or hardcoded unconfined SELinux context was added. These
source corrections passed the clean startup and cancellation test described above.

Source references: [generator](https://github.com/rhinstaller/anaconda/blob/anaconda-44.30/data/systemd/anaconda-generator),
[rescue shell](https://github.com/rhinstaller/anaconda/blob/anaconda-44.30/data/systemd/anaconda-shell%40.service),
[installer service](https://github.com/rhinstaller/anaconda/blob/anaconda-44.30/data/systemd/anaconda.service).

## Keep logs before cancellation

The installer recipe includes a VM-only collector for `/tmp/anaconda.log`, `storage.log`
and `program.log`. It also records SELinux state, selected unit state, the latest 1,000
journal entries and virtual disk sizes/serials. It reads these sources without changing
services or storage. Each log is limited to 2 MiB; missing and truncated logs are reported.
The collector refuses the host and physical installer sessions. It also captures
`/run/apex/installer-preflight.json` when present. If verification stops Anaconda before
it starts, its three usual logs may be absent. Report that absence; a complete serial
transfer does not imply that Anaconda ran.

While the installer VM is running, use `just installer-logs-prepare`. It records the ISO
checksum and VM identity, then prints a guest command and a capture token. Open the
installer's rescue login through its console and run that command there. It sends the
bundle to the VM serial port. It does not require SSH, a NIC or a shared directory.

Before confirming cancellation, run:

```sh
just installer-logs-collect RUN_DIRECTORY TOKEN
```

Use the directory and token returned by preparation. Collection verifies chunk order,
completeness and checksums. An incomplete or damaged transfer fails; repeat preparation
with a fresh token while the installer is still running. Missing or truncated required
logs also fail, with the partial evidence retained. Existing captures are not overwritten.
Neither transfer success nor complete logs mark an installation test as passed.

Captures stay in the private runtime directory. Installer logs can contain account or
storage details; review and redact them before any publication. End-to-end captures
passed both before cancellation and after the failed offline import. Capture logs
before accepting the quit dialog: Anaconda can reboot and discard the live filesystem.
Keep the serial log and record any manual login or service changes with the result.

## Payload trust must precede storage changes

The ISO's detached artifact signature does not authorize its container payload in
`bootc`. The previous ISO inherited Apex's reject-all container policy without an
accepted payload signature. Its import failed after partitioning.

The recipe now signs the frozen OCI archive and retains its compressed blobs in
`/usr/share/apex/payload`. Installer policy rejects everything except that directory
with the selected public key and exact signature identity. It does not authorize
registry downloads. The installed system retains its own reject-all update policy.

Before upstream Anaconda imports or arguments run, a small entry-point guard checks
the policy, manifest digest, configuration digest and signature. It then reads every
blob to verify its declared size and SHA-256. Missing files, symlinks, corruption or a
failed check stop Anaconda. This read can take time on USB; the payload is not copied
into RAM. The guard retains a report in `/run/apex/installer-preflight.json` and runs
again on another invocation, rather than trusting a previous PASS file.

Signature verification uses Skopeo's `OpenImage` API, the policy path used by bootc.
The client requires protocol 0.2.8 and rejects unknown versions, invalid replies and
failed requests. It closes its local socket and child process on failure. A copy-based
check proved unsuitable for the real compressed image: the unpacked store needed a
layer conversion that `--preserve-digests` forbids. The tiny copy fixture did not expose
that difference. The ISO adapter therefore omits the upstream unpacked-store copy and
keeps the signed compressed files already embedded in the derived image.

The clean ISO boot and offline installation described above passed.
Negative VM cases must show that wrong keys, missing signatures, changed manifests,
corrupted blobs and unexpected sources stop before either virtual disk is written.
Record any diagnostic boot arguments or manual startup separately from clean boot.

Run `just test-installer-trust` with an idle builder to exercise the real Skopeo policy
engine on a tiny synthetic image. It tests a signed round trip, a verified copy within
one store, wrong key, wrong identity, missing signature, altered signature, altered
manifest and an unexpected source. The runner now also checks each case through
`OpenImage`. Both sets passed in the builder. They do not prove that the Apex payload
survives ISO construction or that an installation completes.

Fixture keys and their passphrase remain in a private directory inside the VM. Only
the result, command log, script checksum and public keys are exported under
`runtime/signature-policy-tests/`. The runner leaves both the system policy and Apex
policy unchanged and does not mark an installer or update acceptance check as passed.
Fixture keys are not release keys.

References: [container policy](https://github.com/containers/image/blob/main/docs/containers-policy.json.5.md),
[Skopeo copy and signing](https://github.com/containers/skopeo/blob/main/docs/skopeo-copy.1.md),
[OpenImage verification](https://github.com/containers/skopeo/blob/v1.22.2/cmd/skopeo/proxy.go),
[proxy protocol](https://github.com/containers/skopeo/blob/v1.22.2/docs-experimental/skopeo-experimental-image-proxy.1.md),
[osbuild's container-copy stage](https://github.com/osbuild/osbuild/blob/v193/stages/org.osbuild.skopeo).

## Installed payload checks

The signed `dir:` payload's manifest must retain the selected OCI digest. Require
`bootc status` after installation to report that same digest. Matching only the image
configuration ID is insufficient: layer compression can change the manifest without
changing the configuration ID. The signed-payload ISO's installed boot retained the
original manifest digest, as recorded above.

Offline installation, user creation, ISO removal, installed boot and non-target disk
preservation must be repeated when the installer changes. The first diagnostic TUI
only exposed language, time and storage.
The Silverblue profile inherits Workstation's hidden `UserSpoke`; Apex overrides this
in the installer only. It keeps the root-password screen hidden and exposes manual
user creation. Image construction validates the effective Anaconda configuration and
records it in the signed artifact inventory. The earlier unsigned-payload ISO accepted
account choices but failed before they could be tested. The current signed-payload ISO
completed that workflow and passed password login and sudo. The private-account QCOW2
is a separate test path; it does not prove the installer's account workflow.

Sources: [Silverblue profile](https://github.com/rhinstaller/anaconda/blob/anaconda-44.30/data/profile.d/fedora-silverblue.conf),
[Workstation profile](https://github.com/rhinstaller/anaconda/blob/anaconda-44.30/data/profile.d/fedora-workstation.conf),
[configuration loading](https://github.com/rhinstaller/anaconda/blob/anaconda-44.30/pyanaconda/core/configuration/anaconda.py).
