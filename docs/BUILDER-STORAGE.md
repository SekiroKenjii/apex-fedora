# Builder storage

The builder launch gate requires 180 GiB free on the host. A 160 GiB sparse virtual
disk can grow as builds write data, even when files are later removed inside the
guest. Do not lower the gate to start another build or delete candidate evidence to
make room.

## Offline compaction

`just builder-compact` replaces the builder's QCOW2 container after complete
validation. Run it only with explicit authorization to replace that file. All Apex
VMs must be stopped. The command takes both the build and VM locks and accepts only
the exact `builder.qcow2` under private runtime storage, with a validated file-backed
chain. It refuses internal snapshots, persistent bitmaps and corruption flags.

The command creates a separate compressed QCOW2. The original remains in place while
conversion runs. It records the source checksum and capacity, checks both images with
`qemu-img check`, and compares all guest-visible data with `qemu-img compare`.
Different allocation maps are expected after compression; virtual capacity must still
match exactly. The copy is standalone, and the original base file is left intact.

Conversion stops if host free space falls below 12 GiB. Failed or insufficiently small
copies remain for inspection; they do not replace the original. Replacement also
requires enough projected free space to satisfy the unchanged builder launch gate.
Such a retained copy can occupy nearly as much space as the original. Review it
before attempting another conversion; cleanup or reuse needs a separate decision.

After validation, the tool flushes the new file and atomically replaces only the
builder path. Its old QCOW2 byte layout is no longer retained. Guest files, including
build logs and private signing keys, remain in the verified copy. This operation does
not delete exported artifacts, run a guest filesystem repair or mount a host disk.
Keep the compaction report with the following builder boot and build results.

QEMU documents offline image use, compression and comparison in its
[disk image utility reference](https://www.qemu.org/docs/master/tools/qemu-img.html).
Comparison establishes guest-visible data equality, not that the OS will boot or
that a future write cannot exhaust storage. Check resources again before launching.

## Reuse a verified copy

If the copy passed comparison but failed the space requirement, keep it while
reviewing exact generated caches or duplicate downloads. Do not start another
conversion. Verify an independent complete copy before removing an ISO cache, and
record the removed file's checksum and recovery location. Retain candidate images,
failed-test evidence and the rescue medium.

After the storage prerequisite and replacement are approved, use the retained
compaction's 32-character ID:

```sh
just builder-finalize COMPACTION_ID
```

Finalization holds the build and VM locks. It rechecks the original chain's identity,
hashes both complete files, checks QCOW2 structure and compares all guest-visible data
again. The retained copy must be standalone, on the same filesystem, with unchanged
virtual capacity. A changed file or failed check prevents replacement. The free-space
threshold is checked before validation and again immediately before replacement.

The original compaction report stays unchanged. A separate `finalize-ID` directory
records the executed source, validation commands, final hashes and outcome. The new
file and both containing directories are flushed. Only the approved builder path is
replaced; its old QCOW2 layout is not kept after success.

Host compaction does not free the guest filesystem. Once the builder starts, inspect
its available space and exact regenerable caches before starting a build. Keep
signing keys, source locks, outputs and logs. Any cache removal needs its own scoped
record; do not use a blanket container or filesystem prune.

## Duplicate offline fixture blobs

On the builder's Btrfs filesystem, offline fixture builds share identical data
extents between B and the temporary wrong-signature copy. File contents and paths
remain separate; subsequent writes use copy-on-write. The manifest, signatures,
transport markers and private keys are not deduplication targets. The build records
how many blobs and aligned bytes were submitted. It keeps the 24 GiB prerequisite.

For an existing completed fixture, run `guest/dedupe-update-blobs.py --fixture ID`
only inside the idle isolated builder. The helper takes its build lock and first
tests identical ranges, kernel rejection of different ranges and write isolation
on generated test files. It checks each complete blob hash before and after the
operation and preserves inode identity, length, ownership, permissions and link
count. Unaligned tails are left alone. A partial or failed kernel result stops it.
No file is removed, and the report records actual free space after synchronization.

The interface is defined in the kernel's
[file-deduplication UAPI](https://github.com/torvalds/linux/blob/v7.1/include/uapi/linux/fs.h).
[Btrfs documents copy-on-write and deduplication](https://docs.kernel.org/filesystems/btrfs.html).
This storage check does not establish image boot or recovery acceptance.
