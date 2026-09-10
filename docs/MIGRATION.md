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

## P3. The typed kernel

Goal: make safety a type, so a rule cannot be forgotten at a call site.

This is the first phase where the migration rule applies. Every test below was written
against the new interface and observed failing before the module existed.

### What the layer holds

13 modules, 911 lines, covered by 12 test modules and 796 lines of test.

| Module | Replaces |
|---|---|
| `refusals.py` | Refusal identity, so a test matches a code rather than English prose |
| `errors.py` | One `Blocked` type that reported a typing mistake to the operator as a considered refusal |
| `identifiers.py` | The same two regular expressions written out in ten files |
| `verdicts.py` | Four status strings and 34 hand-typed not-tested fields |
| `quantities.py` | Bare numbers for sizes, ports and modes |
| `bounded.py` | The literal 262144 at six sites in two spellings, and the serial chunk kept in step by hand |
| `safepaths.py` | 86 call sites that validated a path and then used the unvalidated original |
| `secrets.py` | Plaintext credentials read from disk by five modules |
| `timing.py` | 24 bare sleeps and 13 hand-rolled polling loops |
| `claims.py` | Environment kinds duplicated between the dispatcher and the evidence module |
| `commands.py` | Argument lists assembled as strings |
| `hashing.py` | Sixteen reimplementations of file hashing |

### Properties the tests establish

The verdict lattice is checked for commutativity, associativity, and the property that
matters: no combination of verdicts raises a set containing no pass to a pass. Not tested is
the identity element, so folding an empty collection yields not tested rather than success.

`SafePath` refuses a symlink, a path outside the runtime root, a traversal escape, a
directory, and a path containing a comma. The comma rule is not decoration: a comma
separates device options, so a comma in a path silently becomes a new option.

`RuntimeRoot` refuses a location outside the permitted bases and a directory that is not
0700. The current `state_dir()` accepts `/etc` and creates it.

A secret cannot be rendered. Its representation is redacted, converting it to text raises,
formatting raises, and serialising it raises.

`FileMode` refuses anything above `0o777`. Every mode the project sets is 0600, 0700, 0644 or
0755, so refusing the setuid, setgid and sticky bits makes an accidental one impossible to
express rather than merely unlikely.

### The layer rule is enforced, not documented

`tests/architecture/test_dependency_rule.py` parses the real import graph and refuses an
upward import, an import of an effect module from a pure layer, a relative import beyond one
level, and any `assert` statement anywhere in the package. All four were tried by hand and
all four were caught. The assert rule matters because `python -O` deletes the statement, and
51 load-bearing checks in the old tree depend on one.

### Two decisions worth recording

The Python floor moved from 3.11 to 3.12. The generic syntax the secret type uses needs it,
and both the host and the target image run 3.14.

The error names do not end in `Error`. The taxonomy is named for what the caller should do,
so the naming rule that would rename `Refusal` to `RefusalError` is disabled with that reason
recorded beside it.

### Result

| Item | Value |
|---|---|
| Kernel modules | 13 |
| Kernel tests | 125 |
| Suite | 840 passed, 15 skipped |
| Strict type check | clean over 17 files |
| Lint on new code | clean |
| Gates green | G1 to G6, plus lint and strict typing |

`migration_red`: every test module under `tests/unit/kernel/` was written first and observed
failing. The layer rule tests were verified by introducing each violation and observing the
refusal.
`golden_change`: none. Nothing the command surface does has changed.
`supersedes`: none. The old modules remain in place and untouched.

## P4. The domain model

Goal: replace the raw dictionaries with types, and read the stored evidence without touching it.

5 modules, 557 lines. Every test was written first and observed failing.

### Host passthrough became inexpressible

`machines.py` holds a closed device union. The current builder assembles a list of strings by
hand and then searches it for six forbidden substrings, which cannot prove the absence of
something nobody thought of. Here there is simply no union member that reaches host hardware,
and the test asserts that no member name contains vfio, usb-host, virtfs, tap or bridge.

Four invariants that live in the middle of the 50-line builder are now properties of the type.
Firmware code is read only and rendering it writable raises. A disposable machine restricts
its user network; a builder does not. Extra disks are refused outside a disposable machine,
capped at two, and refused when repeated or when the same file is also the root disk.

`OwnedTestVm` cannot be constructed for a builder, so a destructive operation that takes that
type as a parameter has proof of ownership in its signature rather than a check each caller
may forget. The identity compares four fields rather than a whole document, so adding a field
to the stored state cannot silently change what a comparison means.

### The stored evidence reads, and nothing was written

`runtimestate.py` parses the version one documents where they lie. Run against the operator's
real store it reads the candidate, 24 evidence records, 193 proof references, 20 superseded
records and 3 archived candidates. The tally is 18 passed and 6 blocked, and the catalogue
holds 62 checks, so the 38 not tested reconcile exactly with the recorded readiness. The
runtime gate reported no difference afterwards.

Malformed input is refused rather than guessed: a short digest, an unknown status and an
unknown environment kind each raise with their own reason.

### Three kinds of version value, separated by type

A release profile has no digest field and a pinned artifact has no release field. Both are
asserted by reading the dataclass annotations, so the separation cannot erode by someone
adding a convenient field.

The practical consequence is in the test that moves to the next release: it replaces five
profile fields and asserts the rendered package name changes, with no other code involved.

A constraint may defer to the image with `SameAsImage`, which is how the kernel and compiler
stop being hand-edited lock fields that a routine erratum invalidates.

Upstream prose carries the release it was validated against and sits beside a structural
field, so a rewording degrades a proof rather than inverting it.

### A weak gate found and fixed

The lint ratchet compared counts across two different configurations. Adding the naming-rule
exemption in P3 silenced one finding in an old file, and the ratchet reported an improvement
that was really a configuration change. The baseline now records a digest of the lint
configuration and refuses to compare against a different one. Verified by changing the ignore
list and observing the refusal.

The opt-in case count moved from 8 to 14 because this phase adds six tests that read the real
store. The suite configuration test caught it, which is what it is for.

### Result

| Item | Value |
|---|---|
| Model modules | 5 |
| Suite | 886 passed, 14 skipped |
| Real store | 24 records, 3 archives, read only |
| Strict type check | clean over 22 files |
| Gates green | G1 to G6, lint, strict typing |

`migration_red`: every module under `tests/unit/model/` was written first and observed failing.
`golden_change`: none.
`supersedes`: none. The old modules are untouched.

## P5. Ports, fakes and the contract suite

Goal: put the outside world behind protocols, and keep the doubles honest.

Four ports so far, each with a real adapter and a fake: process, file system, clock and
identity. 5 protocol modules, 4 real adapters, 4 fakes.

### One specification, two implementations

`tests/contract/` holds the behaviour, and each test runs twice, once against the real
adapter and once against the fake. That is what stops a fake drifting into agreeing with
nothing. Fifty five cases pass on both sides.

The process contract is where the safety property lives. A shell metacharacter passed as an
argument comes back as text rather than being interpreted. An absent program raises a port
failure rather than returning a status. A run that exceeds its deadline raises rather than
hanging. The deadline is a required keyword on the signature, so the 285 call sites that run
without one cannot be written against this port at all.

The file system contract requires the mode on every write. Today the runtime documents land
at 0600 by accident of how a temporary file is created, so the property holds only until
someone changes the helper. Here it is declared and asserted on both adapters.

### The environment is proven by whichever adapter ran

Every adapter declares the environment it attests to. A real one says build; every fake says
simulated. `HostPorts.environment` is the meet of its members, and simulation dominates, so a
bundle holding one fake anywhere attests only simulation.

`require_attestable()` refuses a simulated bundle. The consequence is the one the product
needs: a unit test can construct the entire system and run a whole pipeline, and still be
structurally unable to authorise a recorded result.

The first implementation of that rule tested adapter module names as strings. That was
replaced, because a rule enforced by inspecting where a class happens to live is not a rule.
An architecture test now asserts every adapter declares an environment and that real and fake
declare opposite kinds.

### Result

| Item | Value |
|---|---|
| Ports | 4, each with both adapters |
| Contract cases | 55, run on both sides |
| Suite | 947 passed, 12 skipped |
| Strict type check | clean over 39 files |
| Gates green | G1 to G6, lint, strict typing |

`migration_red`: the contract suite and the port bundle tests were written first and observed
failing.
`golden_change`: none.
`supersedes`: none. Twenty ports remain, and they arrive with the context that needs them.

## P6. Locking, archiving and digesting

Goal: finish the ports that need no guest, and make each one carry a property the current
code gets wrong.

Three more ports, each with both adapters and a shared contract: 7 of the planned twenty
four are now done. The contract suite stands at 93 cases.

### A lock that says who holds it

The current code holds two incompatible behaviours under one name. The machine lock takes an
exclusive flock and blocks until the holder goes away, with no budget and no message. The
remote build lock refuses at once. Neither writes down who holds it, so a refusal cannot say
and a wait cannot be diagnosed.

`AcquisitionPolicy` makes the choice explicit: immediate, or wait for a stated budget. Either
way the holder is recorded in the lock file and a refusal names it. The contract asserts that
a contended lock refuses with the holder in the message, and that a bounded wait gives up
rather than hanging.

### An archive that reads each file once

`export_source` reads every source file twice, once to write it into the tar and once again
to hash it, on every build. The port hashes the bytes it already holds, and the contract
asserts the read count equals the file count. Determinism is asserted directly: bundling the
same tree twice gives the same root, and changing one byte changes it.

Symlinks and non-regular entries are refused rather than followed.

### A cache that cannot become an integrity decision

The digest cache is keyed on device, inode, size and modification time, never on the path, so
a rename cannot serve a stale answer. The contract asserts the property that keeps this an
optimisation: a cold cache produces the same digest as a warm one.

### A gap in the gate, found by the gate

The lint recipe covered four directories and `tests/contract` was not among them, so the new
contract tests were unlinted while the recipe reported success. The lint ratchet caught it,
because those files are not in the baseline and therefore must be clean. The recipe now
covers them.

That is the second time a gate has been saved by another gate rather than by review. It is
also the argument for the ratchet being per file rather than per directory: a directory the
linter never visits still has to answer to the baseline.

### Result

| Item | Value |
|---|---|
| Ports done | 7 of 24 |
| Contract cases | 93, run on both adapters |
| Suite | 991 passed, 12 skipped |
| Strict type check | clean over 48 files |
| Gates green | G1 to G6, lint, strict typing |

`migration_red`: each contract module was written first and observed failing.
`golden_change`: none.
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
just lint                   # style rules over the restructured code
just types                  # strict type check over the package
just gate                   # the standing gate for the current phase
```
