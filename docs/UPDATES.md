# Offline update and rollback fixtures

These tools test the bootc update consumer in a disposable installed VM. They do
not select a new release candidate or install anything on the development host.
The original candidate and its evidence remain unchanged.

## Build the pair

Start the isolated Fedora builder, then run `just update-fixtures BUILD_ID` with a
completed Fedora control image. The helper verifies the frozen parent manifest,
exports public build sources and creates a separate fixture ID. It requires 24 GiB
free inside the builder. No RPM repository refresh occurs.

A adds the existing greenboot fragment separator repair, a fixture marker and an
offline verification policy. B changes only that marker. Both keep the parent's
RPM inventory, kernel and driver settings. Build logs, manifests, public key,
recipes and archive checksum are exported under `runtime/update-fixtures/ID`.
Signing keys stay in the builder. Stop it before launching any test guest.

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

`just test-update ACTION FIXTURE_DIRECTORY ACCESS_DIRECTORY` operates only on that
running test guest. The access directory is the QCOW2's private `test-access` folder.

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

Each operation saves a separate result under the VM run directory. A successful
stage or rollback request does not prove that the next boot succeeds. Keep both
the request result and the post-reboot check. Inspect screenshots and the retained
GRUB/greenboot probe, including warnings, before reviewing the loop.

Manual rollback does not establish the two-failure GRUB fallback. GDM, initramfs,
disk-full and interrupted-update faults still require separate fresh-disk tests.
None of these VM results establishes audio, fingerprint or physical recovery.
