# Migration ledger

The build and test tools are being restructured. This file records what each phase did,
what it proved, and what it deliberately left alone. It is the product-side record; the
working notes stay outside the repository.

The restructure exists because the tools are untyped rather than badly written. Every
domain concept is a string or a dictionary, so each safety rule has to be restated by hand
at every call site, and nothing detects the call site that forgets. The target makes safety
a type and evidence a consequence of control flow.

## What green means

One gate runs at every phase boundary. Rows are added by the phase that introduces the
mechanism, and no row is ever removed.

| # | Gate | From | Meaning |
|---|---|---|---|
| G1 | Full test suite, integration deselected | P0 | No failing test and no new skip |
| G2 | Golden command output matches the baseline | P1 | Observable output unchanged |
| G3 | Recorded effect traces match | P1 | argv, file writes and socket connects unchanged |
| G4 | Runtime inventory matches the P0 manifest | P0 | Nothing under the runtime root was destroyed |
| G5 | Justfile recipe names and arity cover the frozen surface | P2 | Existing commands still work |
| G6 | Advisory lint and typing counts did not increase | P2 | New code meets the house style |
| G7 | Old and new readiness folds agree | P11 | Evidence semantics unchanged while both exist |
| G8 | Generated assets match the handwritten originals | P19 | The generator reproduces what ships |
| G9 | Architecture gates blocking | P22 | Layering, sealing and generated output enforced |

Three fields accompany every phase. They are recorded here rather than in the commit
message, because a commit carries one subject line with no body and no trailer.

| Field | Content |
|---|---|
| `migration_red` | Behaviour tests written against the new interfaces and observed failing before the implementation moved |
| `golden_change` | Required when a phase touches the golden corpus. Names the fields that changed and why |
| `supersedes` | For each deleted test, the identifier of its replacement |

## P0. Freeze the runtime inventory

Goal: make destruction detectable before writing any code that could destroy.

`tools/migration/runtime_inventory.py` records every path under the runtime root and
compares a later state against that record. Files are placed in one of four tiers.

| Tier | Applies to | Recorded |
|---|---|---|
| `digest` | Ordinary files below 100 MiB | Mode, size, SHA-256 |
| `stat` | Files at or above 100 MiB | Mode and size. `--deep` digests them on request |
| `secret` | Private keys, credentials, passphrases | Mode and size only. Content is never read |
| `symlink` | Symbolic links | Mode and target. Links are never followed |

The tiers exist because the root holds 211 GiB across 7 944 entries, of which 1.81 GiB sits
in the 7 889 small files. Digesting the small files takes about six seconds, so the check is
cheap enough to run at every phase boundary. The large files are virtual disks and installer
images whose size and mode still detect truncation or replacement.

Secret-bearing paths are identified by name (`credentials.json`, `id_ed25519`,
`builder_ed25519`), by suffix (`.key`, `.pem`), and by the substring `passphrase`. Public
keys are digested normally, since a `.pub` file carries no secret.

### Result

| Item | Value |
|---|---|
| Entries | 7 944 (7 889 digest, 20 stat, 30 secret, 5 symlink) |
| Total size | 227 010 242 421 bytes |
| Merkle root | `0adf1e94dab1fd4dc43aaa1b77008f1bed78d2507300b977198a3cb5ec43502a` |
| Manifest | `~/.local/state/apex-migration/inventory-v1.json`, mode 0600 |
| Evidence backup | `~/.local/state/apex-migration/evidence-v1.tar.zst`, 17 363 311 bytes |
| Backup digest | `c3953e0e041e53394bb604fa725cce845cdda174551c8dc2f8790c85909a20ba` |

The backup covers the evidence records, the candidate and its history, the trust anchors and
the review documents, which together are 40 MiB and cannot be rebuilt. Private keys and
credentials are excluded from it by name. The builder disk, the exports and the virtual
machine run directories are not in the backup: they are large and reproducible, and copying
them is a separate operator decision.

Verified: recording twice produces the same Merkle root, and a comparison detects a changed
digest, a changed mode, a removed path and an added path. `tests/test_runtime_inventory.py`
covers each of those cases plus the tier rules.

`migration_red`: not applicable. P0 adds a tool and moves nothing.
`golden_change`: none. The golden corpus arrives in P1.
`supersedes`: none.

### Findings recorded, not acted on

`just` is not installed on the development host, although the README instructs the reader to
run `just hooks` and `just doctor`. The recipes were being invoked as plain Python. This
matters for G5, which compares the justfile surface, so P2 either installs `just` as a
documented prerequisite or moves the surface contract to the console script.

The full suite reports 8 skips, all in `tests/integration/`. The default pytest options do
not deselect the integration marker, so an ordinary run collects those cases and reports
them as skipped rather than as not attempted. P1 deselects the marker by default and turns
the skip count into an asserted number.

## Commands

```sh
just runtime-freeze    # record the manifest, once
just runtime-verify    # compare the current root against it
just gate              # the standing gate for the current phase
```
