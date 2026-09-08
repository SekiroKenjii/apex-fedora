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

## Failed update after Apex is installed

Use the GRUB menu to select the last confirmed deployment if automatic recovery fails.
Try its rescue TTY with a password. Capture boot logs before attempting repair.
Do not keep rebooting if the machine loops or the fallback is also broken.

Greenboot must be tested to reject a failed boot after two attempts and select the
known-good deployment. Its userspace checks cannot recover every kernel hang. For a
hang before userspace, record whether a manual power cycle is needed.

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
