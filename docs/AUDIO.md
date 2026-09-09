# ALC294 investigation

No audio fix is included yet. This investigation reads source and existing observations;
it has not written codec registers or changed the working host's audio services.

## Command encoding

The ALSA tool uses `HDA_VERB(nid, verb, param)` to pack the ioctl command. That macro
combines `nid << 24`, `verb << 8` and `param` with bitwise OR. For coefficient writes,
the low eight bits of a noncanonical verb overlap the 16-bit parameter.

| Verb and parameter supplied | Canonical verb | Effective parameter |
|---|---|---|
| 0x477, 0x4a4b | SET_PROC_COEF, 0x400 | 0x7f4b |
| 0x477, 0x74 | SET_PROC_COEF, 0x400 | 0x7774 |
| 0x400, 0x4a4b | SET_PROC_COEF, 0x400 | 0x4a4b |

These are numerical decoding examples, not instructions to write those values. There
is no evidence that the first parameter is electrically correct for this board.
The operator's historical command sequence remains unconfirmed.

Source: [ALSA hda-verb](https://github.com/alsa-project/alsa-tools/blob/03fcd4083ebc6452a1c51efbe8c44fcf6903827a/hda-verb/hda-verb.c#L340)
and the [hwdep packing definition](https://github.com/torvalds/linux/blob/v6.18/include/sound/hda_hwdep.h#L14).
The decoder and tests implement this arithmetic without opening a device:

```sh
python3 tools/apex.py decode-coefficient 0x20 0x477 0x4a4b
```

## ASUS fixups and this board

At upstream commit `df2908090cda368b01ff43709f51890076c56157`, the explicit quirk table
has no M7400QC or 1043:1ab2 entry. Absence from that table alone is not proof of a missing
fix, because pin-based and vendor fallbacks also exist.

The observed firmware pin defaults place the speaker at 0x14 and the microphone at
0x12. The inspected ALC294 ASUS speaker pin patterns use a speaker at 0x17. Another
ASUS microphone pattern expects a microphone at 0x1b, also different from this machine.
Do not assign those patterns to this board without tracing quirk selection.

`ALC294_FIXUP_ASUS_SPK` writes coefficients 0x40 and 0x0f and chains a headset-mic
fix. `ALC294_FIXUP_ASUS_HPE` writes 0x0f only. `ALC294_FIXUP_ASUS_COEF_1B` writes 0x4e4b
and chains another board-specific fix. Those names are not interchangeable recipes.

Source: [ALC294 fixups and pin matching](https://github.com/torvalds/linux/blob/df2908090cda368b01ff43709f51890076c56157/sound/hda/codecs/realtek/alc269.c).

The commit history explains why these writes can affect output. The original UX533FD
fix labels coefficient 0x40 = 0x8800 as setting EAPD high, alongside a separate headset
pin fix. A later patch from Realtek adds coefficient 0x0f = 0x7774 because users of
UX533 and UX534 still had silent speakers. These changes address codec initialization
even when the ordinary audio stack is present. The commits do not document every bit
of those vendor registers, and they do not establish the correct values for M7400QC.
Sources: [original UX533FD fix](https://github.com/torvalds/linux/commit/4e051106730dfc640a8b49db88440af304726f4d),
[Realtek's follow-up speaker fix](https://github.com/torvalds/linux/commit/473fbe13fd6f9082e413aea37e624ecbce5463cc).

The same checks were repeated against stable Linux 7.1.13 at
`81d3924095fd017e473332a9b6dd6dd0e3d9a59b`, matching the candidate's upstream kernel
version. That source also lacks the model/subsystem entry and has the same relevant
pin patterns.
Source: [stable 7.1.13 ALC269/ALC294 driver](https://github.com/gregkh/linux/blob/81d3924095fd017e473332a9b6dd6dd0e3d9a59b/sound/hda/codecs/realtek/alc269.c#L5357).

The Fedora `kernel-7.1.13-200.fc44` source RPM was also inspected inside the builder.
Its `alc269.c` matches the stable file byte for byte, with SHA-256
`46e0746647490cd3a834c1f2429ef287b707e312eced2763c0b647bef27b00ca`.
The spec applies `patch-7.1-redhat.patch` and an empty `linux-kernel-test.patch`.
The only downstream HDA change adds a Framework F111:0010 quirk; it does not change
these ASUS paths. The downloaded SRPM has SHA-256
`7c4a54cbaa4cd03a0b8c35fa4dc8f3fbf578c630a502f5ddb427aaa590f0aca6`.
It came from Fedora Koji over HTTPS and is unsigned. This audit does not approve it
as a kernel build input. Source: [Fedora Koji SRPM](https://kojipkgs.fedoraproject.org/packages/kernel/7.1.13/200.fc44/src/kernel-7.1.13-200.fc44.src.rpm).

Quirk selection first considers a model override and PCI/codec subsystem IDs, then
the full pin table, fallback pins and vendor defaults. There is no ASUS-wide entry in
the vendor-default table. Pin matching ignores sequence/association bits and handles
disconnected pins specially, so comparing raw hexadecimal values alone is insufficient.
The observed speaker/microphone node differences still prevent the listed ASUS patterns
from matching. Confirm the selected fixup on a clean Apex boot before proposing a patch.
Source: [HDA fixup selection and pin matching](https://github.com/gregkh/linux/blob/81d3924095fd017e473332a9b6dd6dd0e3d9a59b/sound/hda/common/auto_parser.c#L898).

## Initialization and resume

`alc294_init` runs its headphone initialization on initial boot or S4 resume and then
runs the common initialization. `alc269_resume` calls codec initialization and restores
the register cache. Common `alc_init` applies stored verbs after amplifier initialization,
then invokes the INIT fixup action. A proposed fix must account for this order and for
runtime power management, not merely make one playback attempt work.

Sources: [ALC294 init and resume](https://github.com/torvalds/linux/blob/df2908090cda368b01ff43709f51890076c56157/sound/hda/codecs/realtek/alc269.c#L876),
[common Realtek init](https://github.com/torvalds/linux/blob/df2908090cda368b01ff43709f51890076c56157/sound/hda/codecs/realtek/realtek.c#L765).

## Next evidence

Trace the selected fixup and collect a clean cold-boot codec/mixer/UCM baseline.
Repeat the source comparison when the candidate kernel changes. Separate the DAC and pin signal
path from external amplifier initialization. Treat vendor coefficient meanings not
documented in source as unknown. Use board documentation or a controlled comparison
before proposing a scoped quirk. Retest both initialization and resume at low volume.

`just hardware-snapshot` collects codec dumps, mixer controls, package versions and
the current model parameter without applying settings. In the September 9 Ubuntu
snapshot, speaker node 0x14 was configured for output, unmuted, connected to DAC 0x02,
and reported EAPD 0x2. The model parameter was unset. Those observations do not prove
that the external amplifier or speakers work, nor do they establish a clean cold boot.
They do not justify replacing the board-specific investigation with a generic EAPD
write. The snapshot remains private and is not evidence of Apex hardware acceptance.
