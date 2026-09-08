# Installer acceptance

The installer is a derivative of the frozen Apex OCI image. It is separate from the
GNOME live trial. Building and signing an ISO does not approve it for a physical disk.

## Current boot findings

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
source corrections still need a rebuilt ISO and a clean boot test.

Source references: [generator](https://github.com/rhinstaller/anaconda/blob/anaconda-44.30/data/systemd/anaconda-generator),
[rescue shell](https://github.com/rhinstaller/anaconda/blob/anaconda-44.30/data/systemd/anaconda-shell%40.service),
[installer service](https://github.com/rhinstaller/anaconda/blob/anaconda-44.30/data/systemd/anaconda.service).

## Diagnostic results are not clean acceptance

Starting tmux manually from the corrected login session opened Anaconda in `install_t`
with SELinux still enforcing. Cancelling from its menu initiated a VM reboot. QMP then
stopped the disposable VM. A complete `qemu-img compare` found both the blank target
and the formatted EFI/NTFS/ext4 fixture unchanged. This confirms that diagnostic run's
disk contents; it is not a passing cancellation test for an untouched ISO.

Capture Anaconda, storage and program logs before accepting its cancellation dialog,
because cancellation can reboot and discard the live filesystem. Keep the original
serial log and record any manual login or service changes with the result.

The bundled container store can contain both the original compressed manifest and a
storage-specific manifest for the same configuration ID. Do not infer the installed
digest from the file named `manifest` alone. Check the image record and the requested
manifest, then require `bootc status` after installation to match the selected OCI
digest. The tested bundle retained the original digest, but no installed boot from
that ISO has been accepted.

Offline installation, user creation, ISO removal, installed boot and non-target disk
preservation remain required. The current TUI only exposed language, time and storage
on its first screen; its user-creation path also needs verification. Do not replace
these checks with the private-account QCOW2 result.
