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
| G5 | Justfile recipe names and operands cover the frozen surface | P2 | Existing commands still work |
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

## P1. Characterisation corpus and effect traces

Goal: prove later that behaviour did not change, without needing a virtual machine.

Three tools do the work. `synthetic_root.py` builds a runtime root from fixed identifiers
and fixed timestamps, so the same input always produces the same bytes. It reproduces the
stored v1 shapes: a candidate with its verification block, evidence records that pass, fail
and block, a record whose proof digest deliberately no longer matches, a superseded record
under `evidence/history/`, an archived candidate under `candidate-history/`, an export
result and a trust anchor. Building it twice gives the same inventory Merkle root.

`golden_corpus.py` runs a declared list of invocations against that root and records the
exit code, stdout and stderr after declared normalisation. `effect_trace.py` runs each
invocation under an interpreter audit hook and records what it actually did: processes
spawned, files opened for writing, renames, copies, directory creation and socket connects.
The hook observes the real interpreter, so the code under test needed no change.

| Tier | Invocations | Content |
|---|---|---|
| `pure` | 37 | Help for every subcommand, coefficient decoding, the report, an absent builder, a valid commit subject |
| `refusal` | 35 | Missing and invalid arguments, an unknown subcommand, six rejected commit subjects, the environment and proof rules, a blocked readiness gate |

62 of 72 invocations perform no side effect at all. The corpus is stable:
recording once and verifying twice from separate scratch directories reports no difference.

### Normalisation is declared

`tests/golden/normalisers.py` maps timestamps, 32-character hexadecimal identifiers,
temporary paths, temporary file names, durations, the Python minor version and host memory
and free-space integers to fixed tokens. A field not on that list must be stable. A field
that appears or disappears is a difference and needs an explicit `golden_change`.

### What the effect traces already show

Two behaviours were pinned rather than fixed, because changing them belongs to a later phase
and changing them silently is what this corpus exists to prevent.

Seven refusing commands create the runtime root before they refuse. `state_dir()` calls
`mkdir(parents=True, exist_ok=True)` unconditionally, so pointing the state directory
somewhere new and running a command that will be rejected still creates that directory. The
target architecture runs the whole preflight before any effect, which removes this.

`readiness` writes `readiness.json` and then exits non-zero. It is a query that persists
derived state. The target recomputes derived data rather than storing it.

`tests/test_golden_corpus.py` asserts both, so a change to either is a deliberate edit.

### Suite honesty

The default pytest options now deselect the `integration` and `golden` markers, and
`tests/test_suite_configuration.py` fixes the number of opt-in cases at 8 and 1. Before this
change every run collected the integration suite and reported 8 skips, so a green run looked
like coverage of checks that were never attempted.

### Result

| Item | Value |
|---|---|
| Invocations captured | 72 |
| Corpus | `tests/golden/commands.json` |
| Fast suite | 688 passed, 9 deselected |
| Gates green | G1, G2, G3, G4 |

`migration_red`: not applicable. P1 adds tools and captures existing behaviour.
`golden_change`: the corpus is created here, so there is no prior baseline to change.
`supersedes`: none.

## P2. Installable package, frozen surface, legacy bridge

Goal: make the new package tree possible without disturbing anything the operator types.

### The surface is frozen against habit, not against the working tree

`generated/justfile.surface.json` records every recipe and its operands as they stood at
the `pre-restructure` tag: 51 recipes. `just surface` asserts the live
justfile is a superset, so a later phase may add a recipe but may not rename one, remove one,
or change the operands an existing one takes. All three cases were checked by making each
change and observing the refusal.

### The package exists beside the old tools rather than replacing them

`src/apex/` now holds the distribution, with a console script entry point and a legacy bridge
that dispatches the 30 current subcommands into `tools/apex.py`. The bridge allowlist only
ever shrinks, which `tests/architecture/test_legacy_bridge.py` enforces against the previous
commit.

Nothing is rewired yet, because equivalence comes first.
`tools/migration/entry_point_parity.py` runs 65 invocations through both entry points and
compares exit code, stdout and stderr. They agree on every one.

### The ratchet holds new code to the house style

`generated/lint-ratchet.json` records findings per file across 132 files. A file in
the baseline may improve but never regress. A file that is not in the baseline must report
nothing, so anything written from here on is clean without anyone having to remember. Ruff is
configured to the project line length of 100 with the rule set named in `docs/STYLE.md`.
Everything under `src/` and `tools/migration/` reports no finding.

### Two hazards found while doing this

The name `apex` collides. `tools/apex.py` and the new `src/apex/` package cannot both be
imported as `apex`, and a stale `tools/__pycache__/apex.cpython-314.pyc` kept resolving first
even after the search path was corrected. The repository sets `PYTHONDONTWRITEBYTECODE` in the
justfile, so the cache only appears when pytest is invoked directly. P20 removes the collision
by deleting the old entry point; until then the search path order and a clean cache matter.

A mechanical lint fix changed behaviour. Replacing `os.readlink` with `Path.readlink` to
satisfy a path rule silently normalised a symlink target from `../../` to `../..`, and the
runtime gate caught it as a difference in a root that had not changed. The exact stored target
is restored, the rule is suppressed on that line with the reason written beside it, and
`tests/test_runtime_inventory.py` now pins the behaviour. This is the failure mode the
migration rule exists for: a style change that no test was watching.

### Result

| Item | Value |
|---|---|
| Frozen recipes | 51 |
| Bridged subcommands | 30 |
| Entry point parity | 65 invocations, no difference |
| Lint baseline | 132 files, 1097 findings |
| New code findings | 0 |
| Fast suite | 706 passed, 1 skipped |
| Gates green | G1, G2, G3, G4, G5, G6 |

`migration_red`: not applicable. Nothing moved; the package was added beside the old tree and
proven equivalent before any rewiring.
`golden_change`: none. Both entry points produce identical output, so the corpus is unchanged.
`supersedes`: none.

## Commands

```sh
just runtime-freeze         # record the runtime manifest, once
just runtime-verify         # compare the current root against it
just golden-freeze <dir>    # record the command corpus, once
just golden <dir>           # replay every command and diff
just surface-freeze <dir>   # freeze the operator command surface, once
just surface                # check the live justfile still covers it
just ratchet-freeze         # record the per-file lint baseline, once
just ratchet                # check no file regressed
just gate                   # the standing gate for the current phase
```
