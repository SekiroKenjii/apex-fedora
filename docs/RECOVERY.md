# Recovery

Keep a copy of this document with the rescue media, readable without network access.
Do not replace the working system while any installation gate is incomplete.

## Before the first installation

1. Identify the USB by stable device ID, model and capacity. Preserve its existing data before any formatting.
2. Prepare Ventoy separately, with an officially verified Ubuntu ISO and the tested Apex live ISO. The build tools do not write the USB.
3. Boot the Ubuntu rescue ISO on the actual M7400QC and confirm input, display and access to the backup destination.
4. Save personal data, partition layout and EFI information outside the internal disk. Verify the backup and perform a restore drill to a safe destination.
5. Store logs on a separate USB data partition. Keep fingerprint state encrypted. Do not persist the whole live root filesystem.
6. Confirm the target partition diagram, including EFI, /boot and root, with the operator. Obtain a separate decision to write the internal disk.

A USB holding two ISOs is still one physical device. If it fails or the backup cannot
be read, stop at a candidate and continue using the existing OS. Do not update Ventoy
at the same time as testing a new kernel.

See Ventoy's [usage instructions](https://www.ventoy.net/en/doc_start.html) and
[partition layout](https://www.ventoy.net/en/doc_disk_layout.html).

## Verify the rescue ISO

Keep the existing USB contents intact during verification. Read the ISO as a regular
file; do not run an installer, format a partition or update Ventoy for this check.
Download `SHA256SUMS` and its detached `SHA256SUMS.gpg` from the official release
directory into a private working directory on the host, outside the repository.

Verify the signing key's full fingerprint against Ubuntu's
[verification guide](https://ubuntu.com/tutorials/how-to-verify-ubuntu). The guide
lists the 2012 CD-image key as
`843938DF228D22F7B3742BC0D94AA3F0EFE21092`. A keyserver lookup or a key bundled with
the download does not establish trust by itself. If Ubuntu changes its signing key,
confirm the new fingerprint through its official documentation before accepting it.
Use a separate GnuPG home so this check does not change the user's personal keyring.

Require a successful detached-signature verification from that key before comparing
the exact ISO filename and SHA-256. A signature failure, an unexpected signer, a
missing filename or a checksum mismatch blocks use of the ISO. Save the downloaded
checksum files, signer fingerprint, verification output and ISO checksum with the
private test evidence. Do not store this evidence on the USB without a separate
operator decision to write there.

Record checksum and signature verification separately from physical rescue boot.
Verification does not prove that Ventoy boots the ISO on this laptop, that the backup
can be read, or that restoration works. Those checks remain prerequisites for the
first installation.

## Failed update after Apex is installed

Use the GRUB menu to select the last confirmed deployment if automatic recovery fails.
Try its rescue TTY with a password. Capture boot logs before attempting repair.
Do not keep rebooting if the machine loops or the fallback is also broken.

Greenboot must be tested to reject a failed boot after two attempts and select the
known-good deployment. Its userspace checks cannot recover every kernel hang. For a
hang before userspace, record whether a manual power cycle is needed.

The September 9 installed-QCOW2 probe found greenboot 0.16.4 active, the Apex health
check successful, `boot_success=1` and no rollback deployment. The generated GRUB
configuration contains the counter fragment. This confirms integration on a healthy
boot, not recovery after a fault. Its final line is `save_env boot_success### END ...`
because the packaged fragment has no trailing newline. GRUB's word rule includes `#`,
so that joined token is not the intended `boot_success` variable. The image recipe now
adds the missing separator and records before/after hashes. The frozen candidate is
unchanged; a new image still needs GRUB environment-persistence and failure tests.
Also measure the actual number of failed boots: the configuration value alone does
not prove the two-attempt limit.

Source: [GRUB 2.12 lexer rules](https://github.com/rhboot/grub2/blob/grub-2.12/grub-core/script/yylex.l#L123).

`guest/recovery-probe.py` collects these prerequisites without triggering a reboot,
rollback or failed service. It refuses physical and non-OSTree sessions. Run it through
the owned VM's private SSH connection and retain its JSON with the VM's digest and
script checksum. A missing rollback image blocks the A/B recovery tests.

The separately signed September 9 A/B fixture now passes trusted offline update,
manual rollback, password login and user-data preservation. It also rejects three
untrusted-input cases through bootc. The repaired image fragment did not refresh
the installed static `grub.cfg`; its old joined token remains present. Test that
configuration migration before faulting the boot counter. Bootupd's report that
BIOS/EFI binaries are current is not proof of a current GRUB configuration. See the
[fixture procedure and results](UPDATES.md).

Subsequent fault tests found that the configured value 2 permits three failed boots
with greenboot 0.16.4. After a VM-only repair of the installed GRUB separator, GDM
failure caused automatic rollback to A. A fresh overlay using one retry returned to
A after exactly two failed boots. Password TTY login and password sudo also passed
after fallback in the original run. The source preset now uses one retry, but no
rebuilt candidate has been accepted. Production static-configuration migration
remains blocked. See the [fault procedure and limits](RECOVERY-TESTS.md).

`bootc rollback` selects the previous deployment's boot entry. It does not restore a
formatted Ubuntu installation, and it does not revert all mutable user data. Read the
[bootc upgrade and rollback documentation](https://bootc.dev/bootc/upgrades.html).

## No working deployment

Boot the tested Ubuntu rescue ISO. Inspect disks without writing them. Use the verified
backup and the saved partition/EFI information to choose a restoration procedure.
Restoration can overwrite data, so confirm its source and destination before proceeding.
If those cannot be established, stop and preserve the disk for recovery.

There is no previous Apex deployment during the first installation. That risk is handled
by tested external restoration, not by bootc rollback.
