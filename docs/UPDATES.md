# Offline update and rollback fixtures

These tools test the bootc update consumer in a disposable installed VM. They do
not select a new release candidate or install anything on the development host.
The original candidate and its evidence remain unchanged.

## Build the pair

Start the isolated Fedora builder, then run `just update-fixtures BUILD_ID` with a
completed Fedora control image. The helper verifies the frozen parent manifest,
exports public build sources and creates a separate fixture ID. It requires 24 GiB
free inside the builder. No RPM repository refresh occurs.

A adds the greenboot fragment separator repair, the tested one-retry preset, a
fixture marker and an offline verification policy. B changes only that marker. Both
keep the parent's RPM inventory, kernel and driver settings. Build logs, manifests, public key,
recipes and archive checksum are exported under `exports/RUN/output` in the runtime root,
where `RUN` is the fixture's identifier. Signing keys stay in the builder. Stop it before
launching any test guest.

This is a development trust root for the test, not the release-signing key. The
public key comes through the builder's authenticated SSH connection. Neither a
key supplied by an untrusted payload nor a detached archive signature establishes
production update trust.

## Verification used by bootc

The policy has a rejecting default and exact `dir` transport scopes for A, B and
two deliberately invalid signature fixtures. Each permitted scope requires a
sigstore signature with the trusted public key and an exact signed image identity.
The separate untrusted-source path has no exception to the rejecting default.
The builder's own policy is not changed.

The installed guest runs `bootc switch --enforce-container-sigpolicy --transport
dir PATH`. This is an OS update operation, not just a Skopeo preflight. Bootc
supports local transports and records whether the container policy is required;
see the [switch reference](https://bootc.dev/bootc/man/bootc-switch.8.html),
[version 1.16.10 implementation](https://github.com/bootc-dev/bootc/blob/v1.16.10/crates/lib/src/cli.rs)
and [containers/image policy specification](https://github.com/containers/image/blob/main/docs/containers-policy.json.5.md).

This offline transport does not test registry TLS, credentials, network delivery,
remote signature discovery or production-key rotation.

## Run one operation at a time

Use a fresh overlay of the private-account QCOW2 built from the selected parent.
Start it with `test-vm --guest-ssh`. The existing VM helper accepts only file-backed
QCOW2 chains under runtime storage. It binds SSH to localhost and restricts guest
outbound networking. No builder runs alongside it.

`just test-update ACTION FIXTURE ACCESS_DIRECTORY` operates only on that running test
guest. The fixture is named by its identifier or its export directory; the access
directory is the QCOW2's private `test-access` folder, whose credentials and key reach
the guest as the disposable account, and every privileged step runs through that
account's password.

1. `provision` transfers and hashes the signed archive, checks every payload file,
   saves the original reject-only policy and installs the fixture policy in this
   disposable guest. It creates a user-owned sentinel file. This explicit trust
   bootstrap is a test customization, not an acceptance test of release enrollment.
2. `switch-a` stages A through the policy-enforced bootc consumer. Reboot the guest
   separately, then use `check-a` to check the booted digest, immutable marker,
   critical services, password login, Wayland, rendered window and sentinel hash.
3. Shut down A and retain its disk as the backing file for separate fresh overlays.
   Run `wrong-key`, `unsigned` and `untrusted` in their own overlays. Each requires
   a policy-specific error and unchanged bootc deployment state. A connection error
   or missing file cannot pass. The helper refuses a second fault in the same run.
4. In another fresh A overlay, `forward` stages B. Reboot and run `check-b`.
   `rollback` requests the previous A deployment without rebooting automatically.
   Reboot separately and run `check-a` again with networking still restricted.

Each operation is one run and saves its report as `update.json` under that run's
export directory, with every unit request and answer, the state before and after,
and the failure when it did not pass; a check keeps its screenshots beside it. A
successful stage or rollback request does not prove that the next boot succeeds. Keep
both the request result and the post-reboot check. Inspect screenshots and the retained
GRUB/greenboot probe, including warnings, before reviewing the loop. The guest must
already be running; a failure leaves it available for diagnosis, and cleanup and
reboot remain separate operations.

Manual rollback does not establish the two-failure GRUB fallback. GDM, initramfs,
disk-full and interrupted-update faults still require separate fresh-disk tests.
None of these VM results establishes audio, fingerprint or physical recovery.

## September 9 results

Fixture `98fbb47d0a1247f889ca5ee5bb93dbae` completed these checks with bootc 1.16.10,
greenboot 0.16.4, GNOME Shell 50.4 and kernel 7.1.13-200.fc44:

- A: `sha256:9fad27723a5b2d14f5f3613f3d280013ff3860e3fb7341cdbaf443b91767d8b8`.
- B: `sha256:71908eb3653d35062ddcdd41778b27d956e566596ef204bb0a9a4cfa51f5e76d`.
- The real bootc consumer accepted A and B and recorded `containerPolicy` verification.
- Wrong-key, unsigned and untrusted-source inputs were rejected in three fresh
  overlays. Each left deployment state unchanged. The entire A backing disk's
  checksum remained unchanged after all rejection tests and the forward/rollback run.
- A to B and manual rollback to A passed. Each tested deployment reached password
  login, Wayland and a visibly rendered GTK4 window with SELinux enforcing. The
  boot IDs differed, the user-data checksum matched, and the kernel and initramfs
  checksums stayed identical. Guests used QEMU restricted networking, with SSH
  exposed only on localhost.

Ten operation checks passed. One earlier harness failure is retained: the fixture
marker was root-readable, while the runner attempted a user read. A root read
confirmed its contents; the corrected runner passed without changing either image.
The build used ordinary lint and reported 13 passes and one skip for each image,
with no warning output. Future fixture builds use the project's fatal-warning mode.

The GRUB issue is still open. Both images contain the repaired fragment, but the
installed `/boot/grub2/grub.cfg` retained the old joined `boot_success### END` token
after update and rollback. Bootupd reports the installed BIOS/EFI components at
their latest versions. That status does not establish that the static configuration
was refreshed. Automatic recovery and the two-attempt limit remain NOT TESTED.

Bootc also printed an unsupported-`dir` local-image lookup diagnostic before both
successful imports and policy rejections. Version 1.16.10 probes the unified store
using Podman `image exists`, treating a nonzero result as absence before taking the
OSTree importer path. This is consistent with the observed nonfatal lookup message;
the separate OpenImage rejection and unchanged deployment state establish the
negative results. See [store detection](https://github.com/bootc-dev/bootc/blob/v1.16.10/crates/lib/src/deploy.rs#L518)
and [existence check](https://github.com/bootc-dev/bootc/blob/v1.16.10/crates/lib/src/podstorage.rs#L384).
Do not use that lookup message alone as a signature-test result.

Logs still contain dock theme-node warnings and reboot/service-teardown warnings,
including the previously observed watchdog message. They remain available for
review; this loop does not pass boot-log acceptance. The frozen candidate's checks
were not reassigned to the fixture digests, nor were fixture results assigned back
to the candidate. No physical media or host OS configuration was changed.
