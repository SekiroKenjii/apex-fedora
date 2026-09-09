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

After validation, the tool flushes the new file and atomically replaces only the
builder path. Its old QCOW2 byte layout is no longer retained. Guest files, including
build logs and private signing keys, remain in the verified copy. This operation does
not delete exported artifacts, run a guest filesystem repair or mount a host disk.
Keep the compaction report with the following builder boot and build results.

QEMU documents offline image use, compression and comparison in its
[disk image utility reference](https://www.qemu.org/docs/master/tools/qemu-img.html).
Comparison establishes guest-visible data equality, not that the OS will boot or
that a future write cannot exhaust storage. Check resources again before launching.
