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

## P7. The registry

Goal: make adding a unit mean adding a file, without trading an editable list for behaviour
nobody can find.

7 modules: provenance, registry, graph, discovery, descriptors, decorators, manifest.

### Four properties, each asserted rather than asserted about

**Open, then sealed, and never both.** Reading before the seal raises, because a read during
import would make import order matter. Registering after it raises, because a unit appearing
once a command is running is a unit nobody reviewed.

**Import-time action is a defect.** Discovery binds refusing ports, whose every member raises
when called. A unit that opened a file or ran a program while being imported would do so
before every guard in the system, so this closes a bypass that runs earlier than anything
else could catch it.

**Order is derived, not written.** `graph.order` sorts by what each unit reads and writes,
breaking ties on the identifier so the result is the same whatever order the units arrived
in. A cycle, a fact nobody writes and a fact two units write are load-time errors that name
the units involved.

**Adding a unit is a diff.** The manifest records identifier, group, environment, summary,
module and line for every unit, captured from the declaring frame rather than written by
hand. A new unit shows up as exactly one added entry.

### The declaration refuses what it cannot honour

A check in the hardware group that declares any environment other than physical is refused at
declaration, so the rule that currently exists as two separate literal comparisons in two
functions now exists once, in the type. A check declaring a simulated environment is refused
outright, since nothing a fake does can satisfy one.

### The ratchet earned its keep again

Adding a per-file exemption for the refusing ports changed the lint configuration, and the
ratchet refused to compare against a baseline produced under the old one. That is the
mechanism added in P4 working on its first real occasion. Re-frozen at 132 files and 1096
findings.

### What P7 does not do

The full catalogue of 62 checks is not registered here. Each needs a summary that says what
it establishes, and inventing 62 of those would be worse than having none. They arrive in
P10 with the evidence context, sourced from the recorded descriptions and the test protocol.

### Result

| Item | Value |
|---|---|
| Registry modules | 7 |
| Registry tests | 37 |
| Suite | 1029 passed, 11 skipped |
| Strict type check | clean over 56 files |
| Gates green | G1 to G6, lint, strict typing |

`migration_red`: every registry test was written first and observed failing.
`golden_change`: none.
`supersedes`: none.

## P8. The pipeline

Goal: express a multi-step operation as a stage set whose order is derived and whose dry run
cannot lie.

5 modules: facts, effects, stages, plans, runner.

### Four properties, each with a test that fails without it

**The whole plan is preflighted before anything applies.** A run that is going to refuse
refuses before it has taken a lock, opened a session or started a machine. For a harness
whose central claim is that nothing improperly touches the host, never starting is a stronger
guarantee than unwinding cleanly afterwards. The test asserts that the first apply happens
after the last preflight, and that a refusal at preflight leaves no apply behind it.

**Preflight purity is enforced by substitution.** During preflight the runner hands the stage
refusing ports, whose every member raises. A stage that runs a program to decide whether it
is ready fails its own test. This is what makes the plan output a review surface rather than
a claim.

**Cleanup is a finaliser returned at acquisition.** A stage returns its release with the
result that acquired the resource, so the unwind order is exactly the reverse of acquisition
and a cleanup cannot be registered for something never obtained. The runner unwinds on every
terminal path, including a refusal part way through.

**Nothing is promoted.** When a run stops, the runner takes the union of the checks the
un-run stages would have attested and reports them as not tested. Refusal to overclaim
becomes a consequence of control flow rather than a discipline someone maintains.

### Order derives from data, and the digest identifies it

`Plan.of` takes a stage set, never an order. The dependency graph from P7 derives the
sequence, so inserting a step requires editing no other step. The digest is computed over the
ordered stages with their reads, writes, effects and attested checks, and it is stable for
the same set and changes when the set changes.

### Two smells removed before commit

The runner briefly carried a `log_sink` parameter nothing used and a condition ending in
`and False`. Both are exactly what the house rules forbid, and both were caught by rereading
rather than by a tool, which is worth recording as a limit of the gates.

`RunContext.facts` and `Plan.stages` shadowed the modules of the same name inside their class
bodies, so the annotations could not resolve. The type names are imported directly, which the
house style allows for typing constructs.

### Result

| Item | Value |
|---|---|
| Pipeline modules | 5 |
| Pipeline tests | 20 |
| Suite | 1050 passed, 10 skipped |
| Strict type check | clean over 62 files |
| Gates green | G1 to G6, lint, strict typing |

`migration_red`: every pipeline test was written first and observed failing.
`golden_change`: none.
`supersedes`: none.

## P9. Settings and targeting

Goal: one typed settings tree, assembled once, and the first real release profile.

### There is no function that reads configuration at the point of use

`project.json` is re-parsed at all nine of its call sites today, four of them inside one
function, and `checks.json` is re-read once per record inside the loop that validates against
it, which opens a window where the catalogue can change mid-evaluation. The loader assembles
the tree once, validates the whole of it, and freezes it.

`explain` answers which layer supplied a value. The question "why is the test machine 4096
MiB" currently has nowhere to look.

### An undeclared variable in the namespace is a hard error

A sweep found 24 distinct `APEX_` variables in use. One belongs to host settings; the rest
are read by guest programs through their own request. Both sets are declared, so a typo in
the host one is refused by name rather than silently doing nothing, and a guest variable is
recognised as a guest concern rather than mistaken for a typo.

That distinction is worth stating: the rule is not that every variable must be a setting, it
is that no variable may be unaccounted for.

### The numbers that were scattered

| Value | Was | Now |
|---|---|---|
| Builder ssh port | one configured value | `defaults.BUILDER_SSH_PORT` |
| Guest ssh port | four uncoordinated literals | `defaults.GUEST_SSH_PORT` |
| Capture limit | six sites, two spellings | `defaults.CAPTURE_LIMIT` |
| Serial chunk | maintained separately in encoder and decoder | `defaults.SERIAL_CHUNK` |
| Boot and shutdown waits | bare sleeps and hand-rolled loops | named wait policies |

### The first release profile is one file

`fedora44_release.py` holds what was chosen: the major, the dist tag, the mock root, the EFI
vendor directory. It holds no digest, and the type has no field that could. Rendering a
package name from it produces `greenboot-0.16.4-0.fc44.x86_64.rpm` and, with the vendor
suffix, `libfprint-1.94.100-1.fc44.apex1.x86_64.rpm`, both of which appear as hand-written
literals in the current tree.

`cachyos_release.py` is declared and deliberately unsupported, carrying the reason. Deleting
it would discard the recorded reason it is blocked and reintroduce a branch the day a second
kernel lineage appears.

### The assert rule earned its keep

The loader briefly narrowed a type with `assert isinstance(...)`. The layer gate refused the
commit, naming the file and line. The check became a real refusal with a reason, which is
what it should have been: a malformed settings file is a condition to report, not an
assumption to state.

### Result

| Item | Value |
|---|---|
| Suite | 1073 passed, 8 skipped |
| Strict type check | clean over 71 files |
| Gates green | G1 to G6, lint, strict typing |

`migration_red`: every settings and targeting test was written first and observed failing.
`golden_change`: none.
`supersedes`: none. `config/project.json` still stands and still feeds the old tools.

## P10a. Corrections the adversarial review found in the committed foundation

Before building the evidence core, eleven agents attacked the design and the code it would
rest on. Three lenses: forging a pass, overclaiming, and losing the irreplaceable data. They
returned thirteen fatal findings, six of which were defects in code already committed rather
than in the proposed design. Those six were verified by hand against the source and fixed
here. The evidence core follows in the next commit.

### Readiness cannot be a lattice rollup

`verdicts.meet` has not tested as its identity, which is correct for combining what one run
observed and wrong for deciding whether every check passed. Folding a catalogue of 62 where
38 were never run reports the verdict of the 24 that were, so `meet(PASS, NOT TESTED)` is
PASS and a readiness gate built on it would report ready with 38 checks untouched.

Worse, retraction would raise it: superseding a blocked result with not tested lifts a group
from blocked to pass, which is the opposite of what withdrawing a result should mean.

`verdicts.require_all` is a conjunction over every check and returns false for an empty set.
`verdicts.claims_less` orders verdicts by how much they assert, which is a different order
from the lattice, and a test asserts the two disagree on exactly the case that matters.

### An allowlist, not a denylist of one value

`HostPorts.require_attestable` rejected simulation and returned whatever else it found. That
is a denylist with one entry. It is now an allowlist, and it accepts an expected kind: asking
a bundle of host adapters to prove a physical laptop is refused rather than answered.

The deeper point is recorded rather than papered over. Every real adapter declares a build
environment because every one of them runs on the host. A class attribute is a declaration,
not a proof, so a check that requires a virtual machine or a physical machine cannot be
satisfied by this bundle at all, and now says so.

### Two clocks, because they answer different questions

`ClockPort.now` returns a monotonic reading and measures waiting. It cannot produce a
`recorded_at`, and a monotonic float written into a record as a timestamp would be
meaningless after a reboot. `WallClockPort` is separate, renders the same shape the stored
records already use, and nothing that decides anything reads it: ordering comes from the
sequence number, so a clock that jumps cannot reorder evidence.

### Adopting a root is still a check

`RuntimeRoot.adopt` accepted any path. It exists so a test and the composition root can hand
in a directory they made, but a root accepted without checking makes every containment rule
below it optional. It now refuses a symlink, a file, an absent path and any mode other than
0700. No existing caller changed, which means they were all already correct.

### An append-only log needs an append

`FileSystemPort` had four operations and none of them could add a line durably. A chain built
out of read-modify-write is not append-only. `append_line` opens with `O_APPEND`, fsyncs the
file, and fsyncs the directory when the file is created. The fake can be told to fail after a
given number of appends, so the disk-full path is testable.

### Two findings recorded for the evidence core rather than fixed here

The legacy `select-candidate` renames the whole `evidence/` directory into
`candidate-history/`. Any new store placed inside it would be swept away by one legacy
candidate selection, so the new store goes beside the old tree and never inside it.

Rotated evidence is not private. `shutil.copyfile` at `evidence.py:121` writes the history
copy with no mode, so 20 files under `evidence/history` and 12 under `candidate-history` are
group-writable and world-readable while the 24 current records and 275 proof files are 0600.
The parent directories are 0700, so this is a policy violation rather than an active leak,
and it becomes a leak the moment a directory mode changes.

### The catalogue is sourced

All 62 check summaries were sourced from the real evidence records, the archived candidates
and the committed documentation. None had to be invented. They land with the evidence
context.

### Result

| Item | Value |
|---|---|
| Fatal findings in committed code | 6, all verified and fixed |
| Suite | 1115 passed, 8 skipped |
| Strict type check | clean over 74 files |
| Gates green | G1 to G6, lint, strict typing |

`migration_red`: every correction was written as a failing test first.
`golden_change`: none.
`supersedes`: none.

## P10b. The catalogue and the readiness fold

Goal: make the installation gate a decision over registered units, and prove it means what
the old one meant.

### The catalogue is 62 registered units, sourced not invented

Five agents read the real evidence records, the archived candidates and the committed
documentation, and produced a summary for every check saying what it establishes. None had
to be generalised from the identifier alone. Each module records where its summary came
from, so a reader can check the claim.

Each check declares the environment that may satisfy it, the proof kinds it accepts, and the
scope limits the operator already wrote down. The hardware rule that today exists as two
literal comparisons in two functions is now a property of the declaration: a hardware check
that names any environment but physical is refused when the module is imported.

`config/checks.json` still stands and still feeds the old tools. A test asserts the
registered set equals it exactly, so the two cannot drift while both exist.

### Readiness is a conjunction and does no input or output

`evaluate` receives resolved records and returns an outcome. It reads nothing, so every
decision is tested directly: an empty catalogue is not ready, one untested check among passes
is not ready, a record bound to another build is blocked, a pass without proof is blocked,
two records for one check is a fault, and the result does not depend on the order records
arrive in.

A detected fault becomes blocked and never not tested. That distinction is the point: the old
code drops a record whose proof no longer matches and lets the check fall back to not tested,
recording the problem in a separate error list that the verdict does not reflect, so a tamper
and a check nobody ran end up looking the same.

Proof bytes are re-hashed on every resolution with no cache. That is the one integrity
property the old code genuinely has, and it is not a performance defect to remove: a digest
trusted from metadata is a digest an editor can change. It costs 0.13 seconds on the real
store.

### Shadow mode agrees, and the one divergence is declared

`just readiness-shadow` runs both folds against the real store. Both are read only: the old
`evaluate` is a pure read and the new fold touches nothing. On the operator's store they
agree exactly: 18 passed, 6 blocked, 38 not tested, and the same installation verdict.

The synthetic store carries a deliberately altered proof, and there the two differ by design.
That class is named and accepted; anything else fails the gate.

### The environment vocabulary was too fine, and shadow mode found it

The sourced catalogue assigned installer-vm and live-vm to seven checks. The stored records
say only vm, because the old vocabulary has four kinds. Requiring a distinction that no record
can express would have blocked seven passing checks on the strength of a refinement that is
mine, not the operator's.

The catalogue now requires vm for those seven and records the finer environment as a scope
limit. This is exactly what shadow mode is for: it turned a silent downgrade into a decision.

### The package is called attestation, because the guard was right

The first attempt named the package `evidence`. The pre-commit guard refused every file in it.
The guard treats any directory component named `evidence` as private, which is the rule that keeps
the runtime evidence store out of Git. That rule is doing its job, and loosening it to let source
code through would have widened a security boundary to accommodate a name.

The package is `apex.attestation` instead. It is also the better name: the package mints and judges
attestations, it does not hold evidence. The guard stays as it is.

The guard's path policy is one boolean of 306 characters, so the fix had to be a rename rather than
a narrower rule. Decomposing it into per-rule units under `workspace/git/rules/` is P12 work, and it
is recorded there.

### Result

| Item | Value |
|---|---|
| Registered checks | 62, none invented |
| Suite | 1145 passed, 7 skipped |
| Shadow on the real store | agrees, no divergence |
| Strict type check | clean over 145 files |
| Gates green | G1 to G7, lint, strict typing |

`migration_red`: the catalogue and fold tests were written first and observed failing.
`golden_change`: none. The command surface is untouched and legacy remains the authority.
`supersedes`: none.

## P10c. The proof store and the chain

### A proof is named by what it contains

The v1 store names a proof by a path chosen when the record is written. Anyone who can write
that path can change what a passing record cites without touching the record. In the new store
the name is the digest, under `objects/<first two characters>/<digest>`, so altering the bytes
moves the object and the citation stops resolving.

The measured effect on the current store: 295 proof files hold 226 distinct digests, so content
addressing removes 22 per cent of the bytes. One screenshot is stored nine times.

### Bounding a read at the recorded length hides an append

The first version read each object with a limit equal to its recorded length. A test caught what
that does. Appending bytes to an object leaves the first `n` bytes unchanged, the read truncates
to exactly those bytes, and the digest matches. The load passes while every other reader of that
file sees the appended content.

The read now asks for one byte more than the record claims and refuses any length that is not
the recorded one. Still bounded, and growth is detected.

### The chain commits to itself, and the head catches a dropped tail

Each link is the digest of the previous link and the canonical rendering of the entry, so an
edit, a deletion or a reorder breaks the chain at a sequence the report names. Dropping entries
off the end leaves a shorter chain that is internally consistent, so a separate head record
carries the latest sequence and link, and a chain shorter than its head is a break.

Verified on a real filesystem: editing one verdict reports a link mismatch at sequence one, and
deleting the middle entry reports a sequence out of order at sequence two.

### What the message authentication code is worth

The key sits beside the chain, under the same account that can edit the chain. It detects an
edit made without the key and a file damaged by something else. It is not proof against the
person operating the machine. `docs/RECOVERY.md` says so in those words, and no text in this
project may say more.

The code signs the link rather than the entry, and the link already commits to the entry, so a
forger who edits an entry must recompute the link, and recomputing the link does not produce the
tag. Both paths have a test.

### Replay never reads a cached digest

The digest port caches on the stat tuple, which is right for an immutable object store and wrong
for anything a verifier decides on. An architecture test refuses that import anywhere in the
attestation package, so the two cannot be confused when the cache lands in the workspace phase.

### One canonical rendering

Two places were about to hash their own JSON. `kernel/encoding.py` now holds the single
byte-stable rendering, and the plan digest was moved onto it.

### The entry kind has one member

Only recorded results exist today, so that is the only member declared. The field is written
regardless: the chain is append-only, and adding a discriminator after entries exist would leave
older entries without one.

### Result

| Item | Value |
|---|---|
| Suite | 1175 passed, 7 skipped |
| Strict type check | clean over 148 files |
| Chain on the real root | empty, replayed, intact |
| Gates green | G1 to G7, lint, strict typing, chain replay |

`migration_red`: the proof store and ledger suites were written first and observed failing on a
missing module.
`golden_change`: none.
`supersedes`: none.

## P11. The versioned reader and the imported record

### The store version is a registry key, not a branch

`model/storemark.py` reads `<root>/schema.json` once and answers with one of three values:
unmarked, marked with a version, or unreadable. Absence is a positive answer rather than a
fallback, so a mark that exists but cannot be parsed can never be handed to the oldest reader.

A reader registers under the marks it claims. `storereaders/v1_reader.py` claims both the absent
mark and version one. Supporting a later store is one new file in that directory, and two
architecture tests hold that claim to account: every module there declares exactly one reader,
and a mark claim constructed anywhere else in the package fails. Both were checked by planting a
violation and watching them go red.

### Four measured regressions in code already committed

The review that produced this design found these by running the code, not by reading it. Each
was confirmed by hand, and each guard was verified load-bearing by deleting it and watching the
matching test fail.

| Defect | What it did |
|---|---|
| No per-record isolation | One unreadable document made the whole store return nothing |
| Symlinked record skipped silently | The check read as absent while the file sat on disk |
| Proof entry indexed directly | A malformed entry escaped as a bare key error, not a refusal |
| `candidate or found.candidate` | A store with no candidate reported eighteen passes where the code it replaces refuses every record as unbound |

The last one is the sharpest. The shadow gate returns early when there is no candidate, so it
could not have caught it. The v1 reader now drops every record and names the fault.

### Strict readiness withholds a claim; it does not erase a finding

The plan says strict treats every imported record as not tested. Read literally that also demotes
the six blocked records the operator recorded, and blocked is what a detected fault looks like:
an altered proof, a record bound to another build, a pass with nothing behind it.
`readiness._judge` exists so a fault cannot look like a check nobody ran, and the literal reading
undoes that.

So strict narrows to verdicts that permit installation. On the real store it withholds eighteen
passes and leaves six blocked exactly where the default fold put them: 0 PASS, 6 BLOCKED,
56 NOT TESTED, not ready.

The guard originally proposed for this was `claims_less`, and it has none. `NOT TESTED` ranks
below `BLOCKED`, so `claims_less(BLOCKED, NotTested)` is true and the guard passes green on
exactly the erasure it was offered as proof against. The test that replaced it states the
property directly: if the default verdict is not a pass, the strict verdict equals it.

### What a reader declares is stamped on what it produces

`StoreReaderSpec` is handed back to its own read function, so a reader stamps its declared kind
and limits rather than repeating them as constants. `Attestation` refuses three mismatches as
defects: a kind disagreeing with the record, an imported record missing either permanent limit,
and a recorded one carrying a legacy limit. A reader that quietly stopped marking records cannot
construct a value.

The two permanent limits are properties of the v1 format, not of any one record. Its environment
came from an argument instead of the port that ran the check, and its binding to a candidate was
never read back. Re-hashing retires neither.

### Nothing was written under the runtime root

`just runtime-verify` reports the same merkle root as at P0 with zero differences. No mark is
written, no proof object, no chain line. Reading the store creates nothing, and a test compares a
full path, mode and size inventory before and after to keep it that way.

### The golden recipes were broken before this phase

`just golden` and `just golden-freeze` both failed with a missing module. They only ever worked
through pytest, which sets the path, and the gate runs the pytest form, so nothing noticed. Both
recipes now set the path themselves.

### Result

| Item | Value |
|---|---|
| Suite | 1238 passed, 7 skipped |
| Strict type check | clean over 160 files |
| Real store through the versioned reader | 18 PASS, 6 BLOCKED, 38 NOT TESTED, not ready |
| Strict on the real store | 6 BLOCKED, 56 NOT TESTED, 18 withheld |
| Runtime merkle root | unchanged, 0 differences |
| Gates green | G1 to G7, plus the readiness table and the integration cases |

`migration_red`: the mark, attestation, election and retraction suites were written first and
observed failing. The reading suite was written after its implementation, so each of its four
guards was instead proved load-bearing by deletion, which is the stronger check.
`golden_change`: one slug, `help-readiness`. Its usage line gains `[--strict]` and its options
block gains one line. No invocation was added or removed, so the tier counts above are unchanged,
and `help-top-level`, `unknown-subcommand` and `no-subcommand` were confirmed byte identical.
`supersedes`: none.

## P12a. Three defects in the shipped adapters

The workspace design review ran the adapters rather than reading them, and found three faults in
code committed earlier in this restructure. All three are reproduced below and each fix is pinned by
a contract test that was red before it.

### A bundle could silently omit a subtree

`_candidates` filtered on `not path.is_dir()`, and that test follows a link. A symlinked directory
was therefore discarded before anything examined the link, and `rglob` does not descend into one, so
the whole subtree left the bundle with no refusal. Measured on a tree holding
`tools/vendored -> ../elsewhere`: the bundle contained `tools/common.py` alone, and a private key
under the link was simply gone. The bundler this replaces refuses that tree outright.

That is precisely the omission a root over the bundle is supposed to make impossible, so it defeated
the reason the root exists.

### A symlinked source root was followed instead of refused

Declaring the link itself as a root bundled `tools/vendored/id_ed25519` and `tools/vendored/render.py`
under paths that do not exist in the tree. A private key entered the bundle under a fabricated name.

### Overlapping roots hashed a file twice

Declaring both `tools` and `tools/helper.py` produced two entries for one file and two reads, so the
root described a multiset rather than a set of files.

### The walk now exists once

All three defects were present in both bundlers, in duplicated code. The walk moved to
`adapters/sourcewalk.py`: it refuses a symlinked root, returns a symlink rather than filtering it so
the caller refuses it by the rule it already has, and returns each file once.

### A refused lock acquirer erased the holder

`FileLocks.acquire` released in an unconditional `finally`, including on the path where acquisition
had failed. The lock is advisory, so a process that merely opened the file truncated the identity the
real holder had written. Measured across three processes against one holder: the first refusal named
`process 330101`, the second and third said `another process` while that holder still held.

The module docstring says the lock writes the holder so a refusal can name it, and after one refusal
it could not. The release is now guarded on having taken the lock.

`migration_red`: four contract cases, all observed failing first. The three archive cases failed on
both adapters; the lock case failed on the real one only, which is why the contract suite had not
caught it.
`golden_change`: none.
`supersedes`: none.

## P12. The repository rules, and the proof that they are no weaker

### This phase changes no authority

`tools/apexlib/gitguard.py` is not edited, not imported from, not repointed and not deleted.
Neither is the entry point or the dispatch. The guard that runs on every commit today is the same
one that ran before this phase, and it stays the authority until a later phase can show the
preconditions are met.

That is the deliberate call. The guard is a working control: it refused a real commit during this
restructure, which is why one package here is named `attestation` rather than `evidence`. Landing
the rules and the proof without the switch is a complete phase. Landing the switch on top of three
unsolved problems is not, and there are three: `tools/` cannot import the new package at all,
because the name `apex` already resolves to `tools/apex.py`; the new refusal type is not in the
exception tuple the entry point catches, so it would reach the operator as a traceback; and the
lint ratchet has no headroom on any of the three files a switch must edit.

### The 306-character boolean is now eighteen rules

Six rules transcribe the path expression, three the shape checks, five the content checks, and
four refuse things the guard permits today. Five more cover the commit subject. Each is one file
holding one rule and its policy as a typed field, and each carries where it came from: a rule that
restates an existing refusal, or one that adds a new one and says why.

That distinction is what removes the central list of blessed exceptions. Adding a deliberate new
refusal is one new file.

### The relation, and what it is checked over

`just guard-shadow` compares the rules with the guard on 1714 rows and 2526 messages, and asserts
different things of the two configurations.

The transcribing rules must agree in **both** directions. They claim only to restate what already
exists, so a difference either way is a transcription error. Measured: zero, on paths, on modes, on
content and on messages.

The full rule set must never permit what the guard refuses. It may refuse more, but only where a
rule that declares itself an addition is the one that fired. Measured: zero weakenings, 45
strengthenings, every one attributed.

The corpus is the whole repository history and index, plus every shape the guard can tell apart,
generated from the guard's own constants rather than from the new rules. A name dropped during
transcription would otherwise drop its own test case with it.

### The oracle was checked by breaking things

Dropping two names from one rule reports 18 weakenings and names them. Widening one rule with case
folding instead of lowering reports six differences in the other direction, on paths carrying the
long s and similar characters. The self-test removes each transcribing rule in turn and requires
the corpus to notice; nothing is undetectable.

### Four secrets this project writes were not covered

Measured against the real guard: `credentials.json`, `passphrase`, `builder_ed25519` and a bare
`token` all pass it today, and the builder key exists in the runtime root. Only `id_ed25519` was
covered. Four rules close that, and each is attributed as an addition rather than smuggled into a
transcription.

The two generic key names stay in the private-document rule rather than moving to the new one.
Moving them would make them permitted in exactly the configuration meant to prove nothing was
dropped.

### Two corrections found while building the proof

Lowering, not case folding. Ten characters fold into ASCII where they do not lower, so folding
would refuse paths the guard permits. That is still a difference, and the oracle treats it as one.

A rule that never decides alone is not automatically dead. The body rule can never be the only
reason a message is refused, because the subject pattern cannot match across a newline, so it is
subsumed on the verdict and still changes what the operator is told. The coverage check therefore
asks whether removing a rule changes what is reported, not whether it ever fires alone. The
co-author rule turned out to be able to decide alone after all, on a one-line subject that happens
to contain the trailer, and the corpus was missing that shape.

### Result

| Item | Value |
|---|---|
| Suite | 1315 passed, 6 skipped |
| Strict type check | clean over 194 files |
| Weakenings | 0 |
| Transcription differences | 0 over rows and messages |
| Strengthenings | 45, all attributed to a declared addition |
| Runtime merkle root | unchanged, 0 differences |
| Authority | unchanged; the old guard still runs every hook |

`migration_red`: the row parser, the rule boundaries, the message rules and both architecture rules
were written first and observed failing. The context order rule was checked by planting an import
and watching it fail.
`golden_change`: none. No hook behaviour changed, so no recorded output moved.
`supersedes`: none.

## Continuous integration

### The gate is the same one a developer runs

The previous workflow ran three checks: the pre-commit guard, the test suite and a syntax pass.
None of the eight gates this restructure built ran anywhere but on the operator's machine, so a
pull request could be green while the lint ratchet, the readiness shadow, the surface contract and
the guard equivalence had never been looked at.

It now runs `just gate`. The one change that made that possible: verifying the runtime inventory
skips on a machine that has no runtime root. A machine that has never built anything has nothing
to have disturbed, which is the ordinary state in continuous integration and is not a finding.
Recording a manifest still refuses, because that genuinely needs a root.

### The interpreter is pinned, because it was silently deciding results

The suite ran on whichever build the tool runner happened to prefer, and that answer changed
underneath this work. Three interpreters were available here and they are not interchangeable:
two of them do not expose `pidfd_open` at all, which one test needs, and the frozen command
corpus records argparse output that different versions render differently.

`just` now names the interpreter down to the patch and reads `APEX_PYTHON`, and every gated step
runs on it rather than on whatever `python3` resolves to. A gate that passes because of which build
was picked that morning is not a gate.

The patch matters, which the first run on a hosted runner demonstrated: argparse's phrasing for an
invalid choice moved between 3.14.4 and 3.14.7, and the command corpus records argparse's phrasing.
Naming only the minor version left the resolver free to pick a different patch on another machine,
and it did.

That failure also showed the corpus reporting only which field had changed and never what it now
said, which is undiagnosable anywhere except the machine the corpus was frozen on. It now prints
the first differing line from each side.

The test that needs `pidfd_open` now skips where the interpreter lacks it rather than failing.
The production path still calls it unconditionally, so on such a build the power-loss fault would
raise rather than refuse. That is recorded, not fixed here: the right behaviour is to refuse, and
it belongs to the phase that owns the machine context.

### What else the workflow gained

The whole history is fetched, because the repository rules are proved against every path this
history has ever held and a shallow clone would quietly shrink that corpus. Superseded runs are
cancelled. Every action is pinned to a commit rather than a tag. The job carries a timeout, and it
runs on pushes to the long-lived branches as well as on pull requests.

## P13. The commit message hook answers to the rules

### One hook, not three

The plan reads as though the three hooks move together. They are not equally ready, and the
difference is not the corpus. It is whether any gate can see the change.

The commit message hook needs no new code that runs a program. It reads a file and applies five
pure rules, every one of them a transcription, with the oracle reporting no difference over 2526
messages. It is also the only hook with recorded output, so it is the only one whose transfer can
be proved rather than asserted.

That mattered more than it sounds. Making a transfer of the other two inoperative leaves every
gate green, because their only end-to-end assertion is that the word `BLOCKED:` appears, which
both guards satisfy. A change nothing can detect is a change nothing can protect, so the other two
keep their current guard until there is a test that would notice.

With the commit message hook flipped, making the transfer inert now fails ten tests and moves seven
recorded outputs.

### A fault must never permit a commit

Only a refusal from the rules counts as a verdict. Any other exit code, a missing package, an
interpreter too old, or any exception at all is reported and handed to the guard that was deciding
before, which delivers its own verdict.

The first shape of this did not hold. Injecting an ordinary `ValueError` printed
`BLOCKED: not enough values to unpack` at exit 2 and the previous guard never ran, so a Python
internal wore the costume of a policy refusal. A `TypeError` printed a traceback at exit 1, again
with the previous guard silent.

Now all three of `ValueError`, `TypeError` and `RecursionError` print a note naming the fault and
then the previous guard's own refusal, at exit 2. The forwarder has exactly two exits, one verdict
from each guard, and an architecture test counts them.

### What the operator types when a refusal is wrong

`APEX_GUARD=legacy` in front of the same command. It asks the previous guard instead of turning the
check off, and every refusal ends with that sentence, so it is discoverable from the refusal rather
than from a document.

The check is the first thing the forwarder does, before the path is touched and before anything is
imported, so it still works when the package is missing or the interpreter cannot parse it. Both
were verified by deleting the package and by running on an older interpreter.

### Four ways the rules can decline to answer, all ending at the previous guard

The switch is set. The interpreter is below 3.12, which is the measured floor: the package uses
syntax introduced there, and an older one fails to parse it while the guard being replaced works
fine, so a higher floor would narrow a working control. The package is not checked out. Or the new
code raised anything at all. Each prints a note saying which, then the previous guard refuses.

### An empty rule registry is a silent permit

Sealing a registry does not require it to hold anything, and judging with no rules returns no
findings. A registry that loaded nothing would refuse nothing and say nothing, which is the one
failure of a guard that looks exactly like success. The dispatcher now counts what loaded against
what the phase shipped and reports a precondition failure if it is short, which the forwarder reads
as no verdict and hands on. A damaged checkout degrades instead of blocking work.

### A carriage return never survives reading the file

The rule for it cannot fire on this path, because reading a file translates the character before any
rule sees it. The guard being replaced reads the same way, so behaviour is unchanged and this is
recorded rather than fixed: reading the message verbatim would make the new guard stricter than the
one it transcribes, which is a difference the oracle is built to refuse.

### Correction to an earlier entry

P12 recorded that the older tree cannot import the package at all. That is wrong. It is a matter of
which directory comes first on the path, and the shim shipped in P11 already puts the package first.
Running the strict readiness command from an unrelated directory prints its table and exits 2. The
claim was recorded without testing the mechanism this project had already built.

### Result

| Item | Value |
|---|---|
| Suite | 1326 passed, 6 skipped |
| Strict type check | clean over 199 files |
| Hooks transferred | one of three |
| Fault injections falling through | 3 of 3 |
| Runtime merkle root | unchanged |

`migration_red`: the seven authority cases were written first and five observed failing, then two
more once the forwarder existed. The fallthrough property was verified by injecting three exception
types. The transfer was made inert to confirm the gate notices.
`golden_change`: field `stderr` only, on the six commit message refusal slugs. Exit codes and
effects unchanged on all six; `commit-msg-valid`, `help-git-hook` and `help-hooks` confirmed byte
identical; no invocation added or removed, so the tier counts stay at 37 and 35. The text is now the
identity of the rule that refused, where before one sentence stood for four different rules.
`supersedes`: none.

## P14. House style, quality gates, and the first recipe on the pipeline

Goal: write down the rules the tree is held to, measure what the plan only promised, and give
the pipeline a real consumer before any new port is built.

Eight commits, each green on the whole gate, on `work/phase-14-style-gates`.

### The rules exist now

`docs/STYLE.md` states every rule the code under `src/` follows and names how each is held:
a ruff rule, an architecture test, or review. `tests/architecture/test_style_rules.py` holds the
ones a test can: a docstring on every module, no prose that narrates the code being replaced,
module basenames unique within a layer, name imports limited to a declared list, version
literals confined to the release profiles, `print` confined to rendering, and a comment budget.
Twelve docstrings narrated the older tree and were rewritten to describe what stands.

Module names may now carry underscores and are unique by dotted name. The earlier rule, a
basename unique across the whole tree, had produced names chosen for not colliding rather than
for saying what the module holds.

A content rule, `repository.vendor-attribution`, refuses any tracked file that names an
external organisation outside the one package coordinate that legitimately carries one. It is
an addition and says so; the guard shadow shows three strengthenings from it and no weakening.

### Measured, not promised

Ruff now enforces a cyclomatic complexity of 8 and 40 statements per function. It found three
functions over the threshold, not the seven an earlier syntax-tree estimate reported; all three
were split. The lint ratchet was re-frozen twice for the configuration changes, and the count
over the older tree rose from 1 096 to 1 173 because the new rules see it too.

Dead code is checked with vulture at confidence 80 on every gate run. At confidence 60 the
report is dominated by model fields and enum members whose consumers are the contexts not yet
built, so that level is recorded as a review to run after P19 rather than a gate.

Two budgets are tests: no module over 400 lines, a line budget per package, and no module
outside the kernel imported by more than 40 others. The kernel is the shared vocabulary and is
exempt by name.

### The catalogue is data

The 62 check declarations are five TOML files, one per group, read and validated when the
registry seals. A malformed table is a `RegistrationError` before anything runs. The readiness
shadow over the real store is unchanged at 18 passed, 6 blocked, 38 not tested. Provenance
records the file and the line of each `id`.

Forty eight `sourced_from` citations had been cut mid-word by the tool that sourced them. They
are trimmed to a word boundary and marked as excerpts, and a test refuses any summary or scope
limit that does not end a sentence. Several scope limits were cut at a fixed width and closed
with a period by the same tool; they read as sentences and this test cannot tell. P23
re-sources them when it re-attests the physical checks.

### The bundle of ports is typed

`RunContext`, `Stage` and `Plan` take the bundle type as a parameter, and `runner.run` requires
a bundle. The refusing double is one class, `ports.planning.Refusing`, which answers any method
name a protocol declares by raising; a port that grows a method cannot leave a gap in it. A
test calls every declared method of every port through the double and expects the refusal.
`HostPorts.for_planning()` returns the same shape with every member refusing, so a stage plans
against the bundle it will later act with. `HostPorts` now carries the lock, digest and archive
ports beside the first four.

`WallClockPort` folded into `ClockPort` as `stamp()`. The ledger takes a clock. The manual
clock renders a fixed origin moved by however far a test advanced it, so a stamp is
reproducible and still changes when time passes.

### Refusals name what they found

A runtime root that is not a directory is refused as `path.not-a-directory`, not as "not a
regular file". An unknown hook kind is `hook.kind-unknown`, not a settings fault. A check
declaration, a release profile or a wait policy that contradicts itself is a
`RegistrationError`, which is what a declaration fault is, rather than a `Refusal` aimed at the
operator. One enum member with no producer, `command.deadline-required`, was removed.

### The first recipe

`composition/recipes/export_source_recipe.py` exports the repository as a screened source
bundle with a manifest, on four stages ordered by their facts: mint a run identifier, locate
the sources, bundle them, write the manifest. The archive port takes a required screen, and
the screen is the repository rules, so a file the hooks would refuse cannot reach the builder
by another door. The port removes a partial archive on refusal, writes the archive at mode
0600 under a 0700 directory, and reports the archive digest itself, so the manifest stage needs
no digest port.

A `SourceRoot` type names a directory sources are read from; unlike a `RuntimeRoot` it accepts
any mode, because nothing is written below it. The derived plan is frozen at
`generated/plans/export-source.json` and checked on every gate run, so a change to the stage
graph is a diff a reviewer reads.

`tests/contract/test_export_source_parity.py` runs the recipe on real adapters over this
repository and compares every bundled path and digest with the older `export_source`. They
agree on all of them. The archives differ in entry order, because the recipe sorts every path
once and the older export sorts within each declared root; the file set and every digest are
the same. The command surface is untouched: `build` still calls the older export, and the
recipe stands beside it until P18 moves the remote run.

### Result

| Item | Value |
|---|---|
| Package | 141 files, 7 183 lines |
| Fast suite | 1 387 passed, 5 skipped |
| Strict type check | clean over 141 files |
| Lint ratchet | 132 files, 1 173 findings, re-frozen for the new rules |
| Guard shadow | 48 strengthenings, all attributed, no weakening |
| Readiness shadow | 18 passed, 6 blocked, 38 not tested, no disagreement |
| Golden plans | 1 |
| Gates green | G1 to G7, G10 |

`migration_red`: the style rule test was written first and observed failing on twelve
docstrings. The reason-code tests were written first and observed failing eight ways. The clock
port tests were written first and observed failing in the ledger and the contract suite. The
catalogue, the typed bundle and the export recipe were written with their tests rather than
after them; the parity test failed twice on real defects, a missing parent directory and an
archive left group-readable, before it passed.
`golden_change`: none. No command's output moved.
`supersedes`: `test_wall_clock_port.py` by the stamp tests in `test_clock_port.py`; the
refusing-port tests in `test_discovery.py` by `tests/unit/ports/test_planning.py`; the
one-module-per-check test by the one-file-per-group test in `test_catalogue.py`.

## P15. Trust: anchors, signed bundles, negatives, and the locked sources

Goal: make the two things a build must trust, a signed artifact bundle and the reviewed source
lock, into types that are checked before anything is fetched or accepted, and prove the
verifier refuses what it must.

Four commits on `work/phase-15-trust`, each green on the whole gate.

### The readers

`model/bundles.py` parses the signed inventory (`artifacts.json`) once, from bytes, and refuses
every malformed shape by one reason. `model/oci.py` reads the frozen image document and the
configuration digest off the packaged OCI manifest. `model/sourcelock.py` turns the reviewed
lock into types: every image reference pinned to its own digest, every archive with a
checksum, an https address by type and a plain basename by type, every commit a full object
id. The thirteen faults the older tests pin each have their own `RefusalReason`; the older
code reported all of them as one `Blocked` with prose.

Two new kernel types carry the checks: `locators.HttpsUrl` and `locators.Basename`. A download
port that only accepts the first cannot be handed a plain-text address. A source directory
that only accepts the second cannot be steered outside itself.

### Two ports, two adapters each

`SigningPort` verifies a signature over bytes, signs bytes, and generates a key pair. The real
adapter is openssl; the fake is a keyed hash over a shared secret written under two names, so
a changed payload, another key and garbage all fail exactly as the real one refuses them, and
nothing it produces can be mistaken for a signature. A `RejectingSigner` and an
`AcceptingSigner` exist for the callers' failure paths.

`DownloadPort` fetches an `HttpsUrl` into the runtime root against a required digest. Both
adapters write a `.part` file first and settle it only when the bytes match; a mismatch keeps
the part for inspection and never replaces the destination. The real adapter is curl with the
same flags the older code used. Its happy path needs a network and is not in the contract
suite; what both adapters share, and what the suite holds, is the shape of a failure. A
`RefusingNetwork` refuses every fetch, so a run that declared no network cannot reach one.

`HostPorts` carries both, and the planning double covers them with no new code, which is the
point of generating it from the name asked for.

### Verification over the bytes that are parsed

The older verifier ran openssl over the manifest file and then read the file again to parse
it. The plan called that a deliberate double read to catch a swap. It was not a defence; a
swap between the two reads would have parsed an unsigned document. The new port verifies
bytes, and the same bytes are parsed, so there is no second read for anything to slip between.
The invariant became structural rather than procedural.

`trust/verifying.py` then lists the bundle directory through the file port and refuses any
symlink or any regular file the inventory does not name, hashes every named file again with the
digest cache cleared, checks the signed digest against the packaged OCI manifest, and checks
`image.json` against the OCI configuration. Each refusal has its own reason.

`trust/anchors.py` makes provenance a field on the anchor. An anchor with bundle provenance
cannot be constructed, and a key that sits inside the directory it is asked to judge is
refused before anything is verified against it. A `RegularFile` type names a key the operator
keeps anywhere; it is never written through.

### The negatives are units

Four modules under `trust/negatives/`, one per way a bundle can lie: an inventory altered after
signing, a payload that no longer matches, a key nobody trusts, and the key shipped inside the
bundle. Each declares the reason it expects. `trust/exercising.py` verifies the original,
prepares every registered negative in a scratch location, and fails the run if any negative is
accepted or refused for a reason other than the one declared. A test with the accepting signer
shows the exercise catching a verifier that accepts a forgery.

Only the two header documents are ever copied for a negative; a payload case writes a small
stand-in and relies on the verifier refusing at the first mismatch in inventory order, which is
what the older `exercise` relied on too.

### Sources

`config/sourcepins.py` reads the lock out of the checkout and refuses absence, a link and
unreadable JSON, each by reason; nothing recreates it. `trust/acquiring.py` brings every locked
source into the runtime root: a source already present with the right digest is left alone, one
whose bytes changed is fetched again, and the reviewed lock is copied beside the sources only
after every fetch held.

### Parity

`tests/contract/test_verify_parity.py` runs the older `verify` and the new verifier over one
openssl-signed fixture through the six cases the older tests pin. They agree on every one.
`test_sourcepins.py` loads the reviewed lock in this repository and finds the same six sources.

The command surface is untouched. `verify-artifact`, `sources`, `select-candidate` and
`trust-development-key` still run the older code through the bridge. The last needs the guest
shell port to fetch the builder's key over SSH and moves with P17.

### Result

| Item | Value |
|---|---|
| Package | 164 files, 8 587 lines; `trust` 544 lines in 11 modules |
| Fast suite | 1 516 passed, 4 skipped |
| Strict type check | clean over 164 files |
| Contract suite | 106 cases, real and fake |
| Gates green | G1 to G7, G10 |

`migration_red`: the model readers, the two ports and the acquisition were each written after
their tests were observed failing. The verifier and the negatives were written with their
tests; two of those tests were wrong on first run (a fixture that re-signed with the wrong digest,
and an expectation that the accepting-signer case ends in one particular reason) and were
corrected, not the code.
`golden_change`: none.
`supersedes`: none. The older tests remain until their commands move.

## P16. The guest program: one codec, a versioned request, one unit, one wheel

Goal: give the code that runs inside a guest a package of its own, a way to be asked and to
answer that the host can verify, and a proof that it installs and runs from a wheel. The
older `guest/` tree stays until the host side that calls each script has moved.

Four commits on `work/phase-16-agent`, each green on the whole gate.

### The package is `apex.agent`, and the guard learned one exception

The repository guard refuses any path with an `agent` component, because `agent` is the name
of the workspace directory that holds material which must never enter Git. The first attempt
at this phase renamed the package to `apex.guest` for that reason, as P10b had renamed
`evidence`. The operator chose the plan's name instead and asked for the guard to carry the
exception.

The exception is one shape, held identically by the older guard and the transcribed rule so
the guard shadow still agrees in both directions: the component `agent`, spelt exactly so,
is admitted when it sits directly under `src/apex` or directly under one test tier such as
`tests/unit`. It stays private at the workspace root, under `docs/`, under `src/` without
`apex`, under `tests/` without a tier, and in any other spelling. The shadow corpus carries
the admitted shape and its near misses, and both guards' tests pin them.

### One codec on both sides

`agent/serialframe.py` is the framing the older `installer-diagnostics.py` writes and the older
`installerlogs.decode` reads, as one module: base64 in chunks of the shared size, each line
carrying the token and an index, closed by a trailer with the count and the digest. The
decoder is a state machine over lines that keeps at most one line of unread bytes, so a guest
that writes anything at all cannot make the reader hold more than a frame of it. Refusals name
what went wrong: out of order, malformed, over the limit, a checksum that does not match, or
no trailer. A test feeds the older decoder what the new encoder writes and they agree.

The chunk size and the capture limit now live in `kernel/bounded.py` alone;
`config/defaults.py` names them and no longer repeats the numbers.

### A request names its protocol

`agent/requests.py` parses a request and refuses one that speaks another protocol before it
looks at anything else. The request carries the digest of the guest program the host shipped,
so a guest can refuse to run under a build it was not handed. A reply names the unit it
answers for. `agent/agentports.py` is the guest's bundle: a process, its files and a clock, and
nothing that signs, downloads or takes a host lock.

`agent/units/` holds one unit per module, registered by being there and looked up by name.
`state_probe_unit.py` runs the eight observations `guest/probe.py` runs, through the process
port with a bound on output, and records a missing program instead of stopping on it. Its
report keeps the older shape and never claims a visual test.

`agent/main.py` is the console script `apex-agent`: `handshake` prints the protocol and the
installed version; `run` reads one request from standard input and writes one reply, plain or
framed with a token. Standard output carries nothing else.

### The wheel is proved, not assumed

`just agent-wheel <dir>` builds the wheel and prints its digest.
`tests/contract/test_agent_wheel.py` builds it, installs it into a fresh environment and runs
the handshake and the state unit from there, so discovery inside site-packages, the console
script and the protocol refusal are exercised before a wheel is ever copied into a guest.

### The live disk guard runs as it ships

The older test rewrote `[ -b "$device" ]` to `[ -f "$device" ]` and every `/sys`, `/dev`
and `/run` prefix in a copy of the script before running it, so the file most responsible for
not destroying the operator's disk had never been tested in the form it ships in.
`tests/contract/test_live_disk_guard.py` runs the script byte for byte inside an unprivileged
user namespace: fixture directories are bound over `/sys`, `/dev` and `/run`, a real block
node is bound over each fixture device so `-b` is true, and `blockdev` and `mount` are shims on
the path that record what they were asked. All eleven cases the older test pins pass this way.
The older test stays until CI shows the namespace test running there rather than skipping.

### Guest map

`docs/AGENT-MAP.md` lists every program under `guest/` and the live root with its role, its
destination unit or asset, and the phase that moves it. Three files are safety artifacts and
move verbatim.

### Result

| Item | Value |
|---|---|
| Package | 171 files, 9 104 lines; `agent` 506 lines in 7 modules |
| Fast suite | 1 574 passed, 3 skipped |
| Strict type check | clean over 171 files |
| Contract suite | 121 cases |
| Gates green | G1 to G7, G10 |

`migration_red`: the codec, the request and the unit were each written after their tests
were observed failing. The wheel test and the guard test were written with what they test;
the guard test failed on first run because a non-recursive bind of the fixture `/dev` hid the
block nodes bound beneath it, which is a fact about mount namespaces and not about the guard.
`golden_change`: none.
`supersedes`: none yet. `tests/test_live_guard.py` is superseded by the namespace test once CI
runs it.

## P17. Provisioning: the machine, its ports, the chain, the lease, the fixtures

Goal: give the host a typed way to start one machine, stop only that machine, know what
disk it is layered over, and describe every fixture it will boot, all through ports that run
on fakes in the fast suite. The older `tools/apexlib/vm.py` stays until the commands that
call it move.

Six commits on `work/phase-17-provisioning`, each green on the whole gate.

### The machine renders every topology

`model/machines.py` gained the two devices the older `vm.command` could express and the
model could not: a serial socket with an appended transcript, and booting from the attached
cdrom. `VmSpec.build` now takes the monitor and the serial device, the optional usb
controller and usb boot media, and refuses the combinations the older code refused: a serial
socket, a usb controller, extra disks or usb media on anything but a disposable test
machine; usb boot with a cdrom, a network or other than one further disk; a cdrom boot with
no cdrom. A socket path that would not fit `sun_path` is refused where the device is built.

`tests/contract/test_machine_parity.py` renders seven topologies and compares each, word for
word, with what `vm.command` assembles for the same inputs: the builder, a sealed test
machine, an installer test that boots its iso and answers on loopback, two extra disks, a
serial socket, an emulated usb bus, and usb boot. The order of `-drive` and `-device`
arguments decides the addresses a guest sees, so the comparison is on order too.

### Two ports, four adapters

`ports/hypervisor.py` takes a rendered machine and answers with `VmIdentity`: the process
number, the inode of its pidfd, its start time in clock ticks and the inode of its monitor
socket. `spawn` returns only once the monitor socket exists, bounded by a deadline, and a
process that exits before then is a port failure that names the log. `terminate` opens a
pidfd, reads the start time again and compares every field before it signals; a mismatch is
refused and nothing is signalled. `capacity` reports available memory, free space below the
runtime root and whether the accelerator device is accessible.

`real_hypervisor.QemuHypervisor` runs the program detached in its own session with standard
input closed and both output streams appended to the log. Its contract test puts a stand-in
`qemu-system-x86_64` on the path that opens the monitor socket it was given and waits, so
spawning, the identity check, the refusal on a changed identity and the failure on an early
exit are all exercised without a guest. `fake_hypervisor.FakeQemu` records every spec it was
handed and issues identities that a test can make disappear.

The first CI run failed here: the interpreter build uv installs on the runner omits
`os.pidfd_open` although the kernel provides the call, which is the gap the older
`vm.power_loss` fell into by calling it unconditionally. `adapters/pidfds.py` now makes
the two system calls directly when the module does not expose them, so the identity check
before a kill does not depend on how the interpreter was built. `tests/contract/test_pidfds.py`
runs both routes on this host, where the module route exists, by hiding it for the second.

`ports/qmp.py` opens a bounded session over the monitor socket. `real_qmp.UnixQmp` reads
the greeting, negotiates capabilities, matches replies by identifier and skips events; an
error from the machine is a port failure. Its contract test runs a monitor server in a
thread. `fake_qmp.ScriptedQmp` answers from a table, records every command, and can be told
what the guest does on receiving one, which is how the fast suite makes a guest halt when
asked. `HostPorts` carries both, and `for_planning` refuses both.

### The backing chain is a type

`provisioning/backingchain.py` walks a disk the way the hypervisor will: each link is a
regular file below the runtime root, reported as qcow2 by `qemu-img info`, and a link seen
twice is a cycle. The result is `BackingChain`, the disk first and its base last, and
`require_standalone` is how a downloaded base is checked before anything is layered over it.
`overlay` creates the copy-on-write layer for a run and walks it back; it refuses to replace
a file that exists, because an overlay is evidence once a guest has written to it. The
contract test runs on the real tool and on a scripted process fed the same descriptions,
including a cycle the tool itself does not detect.

### The intent before the process

`provisioning/leases.py` holds the two records a machine leaves in the runtime root. The
intent names the role, the run, the run directory, the monitor and the exact command; the
lease adds the identity. `launching.launch` takes the machine lock, refuses if a lease names
a running machine, checks capacity, writes the intent, spawns, and writes the lease, in that
order. A host that dies between the intent and the lease leaves the shape `reclaim` looks
for. Neither record is deleted: a lease is released by writing that it was, and a copy of it
lands in the run directory as evidence.

`shutdown` refuses a lease whose identity no longer names a running machine, sends
`system_powerdown`, waits under the declared budget through the clock port, and only then
terminates, which rechecks the identity again inside the adapter. `power_loss` takes an
`OwnedTestVm`, so a builder cannot be asked, refuses an owner that is not the lease, writes
the fault record before the signal, and kills. `comparing.compare` refuses while a machine
runs, compares every overlay with its source through `qemu-img compare`, and reads the
firmware variables a run started with against what it left. The older tree wrote that
baseline and never read it.

The fast suite drives all of it on fakes: the intent is on disk when a spawn fails, a second
launch is refused, a held lock refuses before anything is written, three kinds of capacity
shortfall write no intent, a guest that halts is stopped and one that ignores the request is
killed after the budget elapses on a manual clock.

### Fixtures, the host side

`provisioning/fixtures/` holds one module per fixture the older `guest/` scripts build or
mutate. What lives there is what can be decided without a guest: the request a builder is
handed, the parser for the report it returns, the derivations the older scripts made in pure
functions, and the refusals that keep a fixture from passing as a release artifact. The
initramfs entry parser, the fault path rule, the rescue verdict, the exact GRUB newline
repair, the observer program, the one-retry configuration, the signing policy and the two
container recipes are each compared with the older script's function in
`tests/contract/test_fixture_parity.py`, on accepted inputs and on refused ones.

One deliberate divergence: `initramfs_fixture.plan_digest` hashes the canonical encoding
every other record uses, while the older `plan_hash` hashes Python's default JSON rendering.
The two halves of that protocol move together in P18, so nothing compares one with the other.

The steps that run inside a guest or the builder, which remount, format, sign and call the
dedupe ioctl, are agent units and arrive with `GuestShellPort` and `ContainerEnginePort`.
`docs/AGENT-MAP.md` says so per row.

### What this phase did not do

The block device probe threshold the plan files under P17 belongs to the `live.observe`
unit, which is guest side and moves in P19. `OwnedTestVm` still carries the role rather than
the whole spec. No command calls any of this yet; `apex machine` arrives with the cli in a
later phase, and until then `tools/apexlib/vm.py` is the authority the operator runs.

### Result

| Item | Value |
|---|---|
| Package | 189 files, 10 857 lines; `provisioning` 1 126 lines in 12 modules |
| Fast suite | 1 719 passed, 3 skipped |
| Strict type check | clean over 189 files |
| Contract suite | 265 cases |
| Gates green | G1 to G7, G10 |

`migration_red`: the machine tests failed first on the two new required arguments; the
launching tests were written before `launching.py` and one of them, the clean stop, failed
once more after the precheck was added because the fake guest had halted before it was
asked, which is what the reaction hook on the scripted monitor now expresses. The contract
tests for the hypervisor, the monitor and the chain were written with their adapters; the
parity tests were written after the code they compare.
`golden_change`: none.
`supersedes`: none yet. `tools/apexlib/vm.py` is superseded once the machine commands move.

## P17a. Two checkers, one contract: ports declare, adapters inherit

Goal: make conformance to a port visible where the adapter is written and checked by the
same engine the editor runs, after the operator found findings in the editor that the gate
did not report. Six commits on `work/typing-hygiene`, each green on the whole gate.

### What the editor saw and the gate did not

`just types` runs `mypy --strict` over `src/apex` only, and no module under `src/` assigns
an adapter to a slot typed as its port; that assignment happens in tests and in the wiring
that does not exist yet. So an adapter could drift from its port and every gate stayed
green. The editor runs pyright over everything, and pyright reported 41 findings on `dev`
once it could resolve pytest. Eleven were configuration: pyright did not know `tools/` is on
the path. The rest had five causes: the monitor adapter named its socket parameter
differently from the port; `SimpleStage` carries callable fields while the `Stage` protocol
declared methods with a named parameter, which pyright treats as part of the contract; the
refusing double was assigned straight into port-typed slots, which pyright does not accept
because it does not consult `__getattr__` when matching a protocol; and the new test tiers
and migration tools indexed `object` and `JsonValue` without narrowing.

### Protocol with the discipline of an abstract base

The operator asked for an assessment of `Protocol` against `ABC`. An abstract base gives an
explicit declaration at the class, an override check by the type checker, and a refusal at
instantiation when a member is missing; it costs nominal typing, so every double and every
legacy object would have to inherit. A protocol whose members carry `@abstractmethod` gives
all three when the adapter inherits it, and stays structural for anything that does not.
Both facts were measured before the change: an explicit subclass missing a member raises
`TypeError` at instantiation, and a structural implementer still passes through the
port-typed slot.

Every port under `ports/` now marks its members abstract, and every adapter under
`adapters/real/` and `adapters/fakes/` inherits the port it implements.
`test_every_adapter_inherits_the_port_it_implements` holds that. The one drift already
present, `UnixQmp.connect(socket_path=...)` against `QmpPort.connect(socket=...)`, was
corrected on the port side first, and pyright reported the fake's remaining mismatch at the
class the moment the fake inherited, which is the behaviour this change exists for.

### The double and the stage

`planning.refusing(name)` is the one place the refusing double is typed `Any`, with the
reason beside it; the eleven slots in `HostPorts.for_planning` and the three in
`AgentPorts.for_planning` call it instead of holding a cast each. `mypy` will not accept a
protocol with abstract members as `type[T]`, so a factory typed by the port was not open.
`Stage.preflight` and `Stage.apply` take their context positionally, since every caller
passes it that way and `SimpleStage` carries them as callable fields.

### Pyright in the gate

`[tool.pyright]` in `pyproject.toml` names the paths and the tiers; `just pyright` runs it
with the same pinned interpreter as the rest of the gate, with pytest resolvable so the
tests type check; `just gate` runs it after `mypy`. Pyright is scoped to `src/`,
`tools/migration/` and the four new test tiers. The legacy tests under `tests/` are left to
the ratchet and go with P21.

### Result

| Item | Value |
|---|---|
| Package | 190 files, `mypy --strict` clean, pyright 0 errors over source, tools and four test tiers |
| Fast suite | 1 725 passed, 3 skipped |
| Adapters inheriting their port | 24 classes across 11 ports |
| Gates green | G1 to G7, G10, plus pyright |

`migration_red`: the architecture test for inheritance was written after the adapters
inherited; the pyright findings were the failing observation for everything else, recorded
on `dev` before any change. `golden_change`: none. `supersedes`: none.

## P18. Composition: the guest shell, and the four builds on the pipeline

Goal: give the host a typed way to reach the builder, and run every build the older
`_execute` runs as a plan of stages whose order is derived, whose refusals happen before the
first effect, and whose host commands are the older ones word for word. Six commits on
`work/phase-18-composition`, each green on the whole gate.

### A script is steps, not a string

`ports/guestshell.py` names a guest by where its shell answers and which key opens it, always
on loopback; a user name that is not a plain name is refused. A `RemoteScript` is a tuple of
steps, each an argument vector; it renders once with shell quoting and joins with `&&`. The
only shell syntax admitted is on a step: discard errors, tolerate failure. `under_lock` wraps a
whole script as one step under the guest's build lock, which is how the older tree's
`sudo flock -n ... bash -c '...'` is composed without a string being written by hand.

`real_guestshell.OpensshGuestShell` renders the same `ssh` and `scp` argument vectors the
older `vm.ssh_args` and its copied lists render, and runs them through the process port.
The process port gained a transcript: a run may append both output streams to a file as
they arrive and return no output, which is how a build that talks for hours is kept without
holding it in memory. `fake_guestshell.ScriptedGuest` echoes any script back unless told to
be strict, records every copy in both directions, and answers a declared script with a
declared exit code. The contract test runs the real adapter against `ssh` and `scp` stand-ins
on the path, so a file sent to the guest comes back through them.

### What is built from what

`model/builds.py` types the request and the record: the two profiles, of which only Fedora
is reviewed; the four artifact kinds, of which three are derived; the record the older
`result.json` holds; and `require_frozen`, which accepts a parent build only when its record
says it completed an image, its frozen document names the manifest on disk, and that manifest
names the image the document claims. Those are the three checks the older `_execute` made
inline, now one function with a test per refusal.

### One plan, three recipes

Nine stages join the four from P14 in `composition/stages/`. `build.freeze` decides in
preflight what is being built from: an unreviewed profile and a derived artifact without a
parent are refused before any stage acts. `builder.check` reads the frozen fact so no guest
is reached before the parent is validated, and `guest.prepare` reads the acquired sources so
nothing is created in the guest before the sources are pinned. The transfer, run, retrieve
and record stages are the older sequence: send the bundle and the frozen document, run the
build under the lock with the transcript at `exports/<run>/build.log`, bring `output/` home
whether or not the build passed, write the record, and fail the run if the guest did. The
record lands before the verdict, so a failed build is never mistaken for one that did not
happen.

`composition/buildplan.py` holds the shared stage set; `image_recipe`, `disk_artifact_recipe`
and `live_artifact_recipe` name the plan and seed the kind. With `export_source` there are
now four recipes on the pipeline, each with a frozen plan under `generated/plans/`. The
derived order puts every local decision before the first remote effect.

### Parity

`tests/contract/test_build_parity.py` runs the older `_execute` with its shell, copies and
build captured instead of performed, and the recipe on the real guest shell adapter over a
recording process port. For each of the four kinds the two argument vector sequences agree
word for word once run identifiers are normalised: the isolation check, the private
directory, the bundle, the frozen document, the locked build script, the ownership step and
the retrieval. `tests/pipelines/test_build_recipes.py` drives the same recipes on fakes and
pins the refusals, the failed build's record, and that preflight only computes.

### The decoder under hostile bytes

`tests/property/test_serialframe_memory.py` feeds the frame decoder sixty four mebibytes in
three hostile shapes and holds the peak under four mebibytes, with at most one line of
unread bytes pending. The specification names one gibibyte; memory that is constant over
sixty four is constant after it, and the fast suite cannot afford the gibibyte. The property
tier is lint checked, type checked and searched for dead code like the others.

### What this phase did not do

Test access for a private QCOW2 fixture, the blueprint the older `execute` writes when asked,
is not offered by the recipes yet; it needs the secrets port. The guest side of the fixtures,
the `ContainerEnginePort`, the canonical plan hash on both halves of the initramfs protocol,
and `kernel = SameAsImage()` for the NVIDIA lock move to the next slice, P18b, which needs
the agent inside the builder. The guest build scripts run as shipped through the guest
shell; `docs/AGENT-MAP.md` says so per row. No command calls the recipes yet.

### Result

| Item | Value |
|---|---|
| Package | 208 files, 12187 lines; `composition` 920 lines in 24 modules |
| Recipes on the pipeline | 4, each with a frozen plan |
| Parity | 4 artifact kinds, host commands identical to the older build |
| Strict type check and pyright | clean |

`migration_red`: the recipe tests on fakes and the parity test were written after the stages,
against the older sequence read from `_execute`; both passed on their first run, which says
the older sequence was transcribed step by step rather than that nothing was learned. The
guest shell contract tests were written with the adapters. `golden_change`: three plans
added, `export-source` unchanged. `supersedes`: none yet; `tools/apexlib/pipeline.py` stays
until the build commands move.

## P18b. The guest side: an engine, a delivery, and the first fixture unit

Goal: give a unit inside the builder the ports it needs, give the host a way to put the
guest program there and ask for a unit, and move the first builder-side fixture script into
a unit that runs the same commands. Four commits on `work/phase-18b-guest`, each green on
the whole gate.

### The engine is a port the guest holds

Every podman and skopeo call in the tree runs inside a guest script; the host has no call
site. `ports/containers.py` is therefore declared with the other ports and implemented for
the guest: a reference carries its transport, a build and a run are requests, a copy
preserves digests and may sign, and the raw manifest is bytes because that is what a digest
is taken over. `real_containers.PodmanEngine` renders the older scripts' arguments through
the process port; `fake_containers.FakeRegistry` answers from tables and records every
build, run, copy and key. The contract test runs the real adapter against a stand-in for
both programs on the path. `AgentPorts` carries the engine and, since a unit hashes what it
produced, the digest port.

### The wire protocol lives below both sides

`composition` may not import `agent`: the layer rule holds that. The request, the reply and
the framing codec are used by the host that asks and the guest that answers, so they moved
from `agent/` to `model/agentwire.py` and `model/serialframe.py`. The agent imports them from
there like everyone else. The reply gained a parser, and the process port and the guest run
gained standard input, which a request travels on.

### Delivery

`composition/agentrun.py` sends the wheel beside the run, unpacks it with `python3 -m
zipfile`, and asks for a unit as root under the guest's build lock, with the request on
standard input and the reply framed under a token. `tests/contract/test_agent_delivery.py`
builds the wheel, unpacks it the same way on this host and runs the handshake and the state
probe off that directory, so the path that needs nothing installed in the guest is proved
where a wheel can be built. On fakes, the unit tests pin the two scripts, the request the
guest receives, and that a refusal, a reply for another unit and a reply that never finishes
each stop the host.

### The first fixture unit

`agent/units/installer_disks_unit.py` is `guest/installer-fixtures.py` step for step through
the ports: the packages, the raw image, its table, the loop device that must belong to the
image, one formatted and sentinelled partition at a time, the two QCOW2 outputs, the report.
`agent/builder.py` refuses any guest that is not the isolated builder before the first step.
`tests/contract/test_installer_disks_parity.py` runs the older script with every program
captured and answered, and the unit on a scripted process with the same answers; the two
argument vector sequences agree. One difference is by construction: the unit waits for a
partition node to exist rather than asking whether it is a block device, because the file
port has no such question and a path under `/dev/loop` is a block device or absent.

### What this slice did not do

The remaining builder-side fixtures need four things the ports do not offer yet: a working
directory for a run, a file copy, a sparse file of a given size, and the free space below a
path. They go to P18c with those additions. The installed-guest fixtures, initramfs and
recovery, go with the faults they exist for in P19. `kernel = SameAsImage()` belongs to the
NVIDIA milestone, and test access to the secrets port.

### Result

| Item | Value |
|---|---|
| Package | 215 files, 12943 lines |
| Ports declared | 14, twelve with a host adapter, the engine for the guest |
| Units | `guest.state`, `fixture.installer-disks` |
| Strict type check and pyright | clean |

`migration_red`: the layer test failed on the first delivery commit because composition
imported the agent, which is what moved the protocol down; the unit tests and the parity
test were written after the unit and passed on their first run, with one normalisation for
the older script's relative output path. `golden_change`: none. `supersedes`: none yet;
`guest/installer-fixtures.py` stays until `just installer-fixtures` calls the unit.

## P18c. The guest side: the three builder fixtures become units

Goal: move the remaining builder-side fixture scripts into units that run the same commands
through ports, adding to the ports only what a unit actually asked for. Five commits on
`work/phase-18c-guest`, each green on the whole gate.

### The ports grew by what was asked

`ProcessPort.run` takes a working directory, because the Ventoy installer is run from the
directory its archive unpacks into. `FileSystemPort` gained `copy`, `link`, `reserve`,
`remove`, `patch` and `free_space`: the copies and hard links the update fixture makes, the
sparse image the medium starts from, the signatures removed from a variant, the one in-place
write the dedupe self test needs to prove copy-on-write isolation, and the free space every
fixture checks first. `ArchivePort` gained `extract` with the data filter and `pack` with a
top-level name. The agent's bundle carries the archive port, the identity port for a
passphrase, and the new `ExtentPort`. Each addition has a real adapter, a fake and a contract
case.

### Three units, three parities

`fixture.ventoy` is `guest/ventoy-fixture.py` step for step: the reviewed request, the inputs
hashed against it, the packages, the upstream archive unpacked and its version read back, a
sparse image attached as the loop device that must belong to it, the installer run against
that device alone from the unpacked directory, the table and the version checked, the two
ISOs copied and hashed again, the QCOW2 written and checked.

`fixture.update` is `guest/update-fixture.py`: the storage check, the payload's manifest
against the frozen digest, two signing keys, the build context, image A over the payload and
B over A, each linted and its packages compared with the baseline, each copied out signed,
then the unsigned, untrusted and wrong-key variants, and the bundle packed for the host.
The older report embedded every command's output; this one names the images, the files and
the digests. Extents are not yet shared on Btrfs from inside this unit; the dedupe unit does
that on a completed fixture.

`fixture.dedupe` is `guest/dedupe-update-blobs.py` over `ports/extents.py`, whose one call is
the kernel's dedupe ioctl with the layout in `model/extents.py`. The self test proves the
same three things: identical bytes share, differing bytes are refused by the kernel, and a
write to one copy does not reach the other.

Each has a parity harness under `tests/contract/`: the older script runs with every program
answered and every file a copy or a key would leave written by the answer, the unit runs on
a scripted process with the same answers, and the argument vectors agree. For the medium
the directory each command starts in is compared too; for the update fixture the bundle
layout both sides leave is compared as well. `podman run` now spells the network option
before read-only, as the older builder scripts do.

### What this slice did not do

The installed-guest fixtures, initramfs and recovery, go with the faults they exist for in
P19. No `just` recipe calls a unit yet; the older scripts stay until the commands move. The
extent contract's real case skips where the temporary directory's filesystem cannot share.

### Result

| Item | Value |
|---|---|
| Package | 222 files, 14183 lines |
| Units | `guest.state`, `fixture.installer-disks`, `fixture.ventoy`, `fixture.update`, `fixture.dedupe` |
| Ports declared | 15, the engine and the extents for the guest |
| Fast suite | 1 836 passed, 5 skipped |

`migration_red`: each unit's tests were written after the unit; the ventoy tests found the
free space check and a missing version marker, the dedupe parity found the container listing
had bypassed the recorded process. `golden_change`: none. `supersedes`: none yet.

## P19a. Verification, first slice: the write path and two observation probes

Goal: close the write side of the evidence store and start the verification context with the
probes that only read. Five commits on `work/phase-19-verification`, each green on the whole
gate.

### Every refusal before the first byte

`attestation/minting.py` is the one way a new result enters the store. It refuses, in this
order, a check the catalogue does not declare, hardware evidence from anything but the
laptop, a bundle that witnesses another environment than the check requires, a simulated
bundle, a proof kind the check does not accept, an empty proof, and a pass with no proof.
Only then does it absorb the proofs and append the entry. The environment is what the port
bundle reports, never an argument. The two half invariants from the specification, the proof
suffix allowlist and the hardware environment at write, are now whole: the read side in
`readiness._judge` stays, because the store on disk is not trusted to have come from this
code. Each refusal has a test that violates it on purpose and checks the chain and the
object store are untouched.

### The file port answers three more questions

`list_directory` lists one level, `resolve` follows every link, `inspect` reports kind,
owner, mode, the security label and, for a device node, its number. The fake follows
declared links on reads and lists declared devices; the contract suite proves both adapters
the same way, with the null device standing in for a block node the real adapter cannot make.

### One snapshot of sysfs

`agent/blockdevices.py` reads `/sys/class/block` once: nine port calls per device, then a
lookup by number or by name costs none. A digest over the listing says whether the tree
changed between two snapshots, which is how the older scripts asked whether a fixture moved
under them. The test takes two hundred devices, counts the calls with a fake that ignores
its own re-entrant calls, and states the bound as a number. The threshold the plan filed
under P17 is met here, where the first caller is.

### Two probes as units, and the host side that asks for them

`live.observe` is `guest/live-probe.py`: the same three guards, the same thirteen programs,
the same five files and two executables, and the block devices from the snapshot.
`ventoy.observe` is `guest/ventoy-probe.py` the same way. A parity harness runs each older
script with every program answered and every file it opens recorded, and requires the unit
to run the same argument vectors in the same order and read every file the script read; the
unit may read more attributes through the snapshot and never fewer.

`verification/` is the sixth context. `probing.ProbeCase` names a unit and the environment
a guest must be in to be asked; `verification/probes/` holds one case per file, sealed like
every other registry, and a test checks that every case names a unit the agent declares.
`probing.observe` asks the guest through `composition.agentrun` and holds the whole reply,
canonically encoded, as a JSON proof for `minting.mint`, so the bytes filed are the bytes
the guest sent.

### What this slice did not do

No stage calls `mint` or `observe` yet; the first is the write-denial fault in P19b, which
needs the snapshot's identity check against the opened node. The remaining probes, the
faults and `generated/os/` follow in later slices. No `just` recipe calls a unit yet.

### Result

| Item | Value |
|---|---|
| Package | 233 files, 15106 lines |
| Units | `guest.state`, `live.observe`, `ventoy.observe`, `fixture.installer-disks`, `fixture.ventoy`, `fixture.update`, `fixture.dedupe` |
| Probe cases | `live.observe`, `ventoy.observe` |
| Fast suite | 1 897 passed, 4 skipped |

`migration_red`: the minting tests found that an empty proof was refused after the first
proof had already been filed, so every citation is now judged before any byte lands; the
snapshot test found the counting fake counting its own re-entrant calls. `golden_change`:
none. `supersedes`: none yet.

## P19b. Verification, second slice: the write-denial faults and the first record

Goal: the two faults that prove the live medium protects its disks become units, and one
stage records what they establish. Four commits on `work/phase-19b-faults`, each green on
the whole gate.

### A port for the one write a fault makes

`ports/blockdevices.py` has one operation: read a range of a block device, write the same
bytes back to the same place, read again, on one descriptor whose identity was checked
against the number sysfs gave for the node. The kernel's refusal is an outcome; a node that
is not the device named is refused before any read. The real adapter cannot be handed a
disposable block device on a development host, so the contract proves the refusals on both
adapters and the accepting and denying paths on the fake only; the live fault in a guest is
where the real path is proven. The agent's bundle carries the port.

### Two faults over one snapshot

`agent/livefixtures.py` holds the rules the older scripts enforced before touching anything:
the blank 48 GiB target and the partitioned 4 GiB sentinel by size, serial, bus and layout;
the one USB fixture by the serial on its USB device; every node read-only, unmounted, not
swapped, not held, and its `/dev` node the device sysfs described. `fault.live-write-denial`
and `fault.usb-write-denial` take one inventory, take it again before every attempt, write
each node's first sector back to it, and stop at the first write that was not denied. The
report says what happened; the host decides what it proves.

The parity harness compares judgements rather than argument vectors, because the older
scripts write with the standard library and not through a program: whether an inventory is
accepted under eleven mutations, what status six write outcomes earn, which devices a run
attempts before it stops, and how the USB parent is found. One spec builds both sides.

### The first record

`verification/faulting.py` names a fault case and turns a report into a verdict and a proof.
`verification/stages/fault_stage.py` makes one stage per case; `mint_stage.py` makes one per
check, folds every report's verdict with `meet`, files every report as proof, and records
once, because the readiness fold refuses a check with two records. Its preflight refuses a
witness the check cannot accept before any guest is asked. `deliver_agent_stage.py` ships the
wheel under the run's directory. `recipes/live_protection_recipe.py` composes them for
`live.disk-protection`, and its plan is frozen under `generated/plans/`.

The environment a record stands in is `claims.witnessed_through(bundle, guest)`: a fake
anywhere in the host bundle makes it simulated, otherwise it is what the adapter that
launched the guest declared. The pipeline test on fakes therefore ends where the design says
it must: every fault runs, the chain refuses `SIMULATED_ENVIRONMENT`, and nothing is
recorded. The recording path is tested on a bundle whose fakes declare themselves real, and
the test says so.

### What this slice did not do

The lock fault needs a child with a capability dropped, which the process port does not
offer yet; it goes with the remaining faults. The witness is seeded by the caller, because
the lease does not yet carry it; the catalogue still says `vm` for live checks, so a live
guest is declared `vm` until the catalogue distinguishes them. No `just` recipe calls the
recipe yet.

### Result

| Item | Value |
|---|---|
| Package | 251 files, 16045 lines |
| Units | `guest.state`, `live.observe`, `ventoy.observe`, `fault.live-write-denial`, `fault.usb-write-denial`, and the four builder fixtures |
| Recipes | four builds and exports, `verify-live-protection` |
| Fast suite | 1 972 passed, 9 skipped |

`migration_red`: the parity found the fake could not model a changed readback under a
denied write; the style rule refused a second `keys.py` in the context layer.
`golden_change`: none. `supersedes`: none yet.

## P19c. Verification, third slice: the lock fault and the store that reads its own records

Goal: the last fault over the live fixtures, and a reader for the records the previous slice
started writing. Four commits on `work/phase-19c-lock`, each green on the whole gate.

### A run may drop a capability, or refuse to run

`ProcessPort.run` takes `variables`, added to the inherited environment, and `dropping`, a
set of capabilities removed from the child's bounding set between fork and exec. The real
adapter applies the restriction with `prctl` in the child; a host that cannot apply it fails
the run rather than running it unrestricted, and the contract suite states that as the only
two outcomes. The lock fault needs both: the guard's denial must be read in one locale, and
the guard must run without `CAP_SYS_ADMIN` so the kernel refuses its lock.

### The lock fault

`fault.live-lock` is `guest/live-lock-fault.py`: the guest must be at the pre-mount
breakpoint with the reviewed guard on disk, checked by digest against an argument the host
supplies; the sentinel fixture is made writable behind a stopped udev queue; the guard is
run in a restricted child; the read-only flag and the latch are read back; the fixture is
restored and the queue restarted whatever happened. Every step that does not go as the fault
needs is recorded rather than raised past the cleanup, so the report always says what was
done. The parity harness runs the older script with its files and programs answered in place
and the unit on a process fake that moves the tree the same way: the argument vectors, which
of them ran restricted, and the statuses agree for the passing run and two failures.

The lock fault has no recipe yet. It runs in a different boot from the write-denial faults,
and all three establish `live.disk-protection` together; composing them across boots needs
the machine stages that arrive with `apex machine`.

### The store reads its own records

A version two mark elects `storereaders/v2_reader.py`. It reads the legacy documents exactly
as the version one reader does, still imported, and then the chain, whose entries were
witnessed by ports and carry no permanent limit. Where a check has both, the chain's latest
entry counts and the imported one is superseded. A chain that does not replay is a named
fault at the sequence where it breaks, and the entries before the break still count because
each carried its own tag and link. A chain with no key beside it counts nothing and says so.

The key lives beside the chain, at `attestation/ledger/key` under mode 0600, laid down by
`Recorder.open` the first time a root is opened for writing, which also writes the version
two mark. A version one store becomes version two by that mark alone. `verify-chain` prefers
the key file and falls back to the environment variable it used before.

The read path takes a file port. The legacy reader ignores it and reads the documents where
they lie, as before; the chain and the objects are read through it, so the same reader serves
a root on disk and a store in memory.

### What this slice did not do

The remaining probes (recovery, installed recovery, desktop render and theme, diagnostics,
installer diagnostics), the installer faults and the fingerprint fixture test follow. The
witness on the machine lease and the recipe across boots go with `apex machine`. Nothing
opens a store for writing yet outside the tests.

### Result

| Item | Value |
|---|---|
| Package | 254 files, 16583 lines |
| Units | `guest.state`, `live.observe`, `ventoy.observe`, `fault.live-write-denial`, `fault.usb-write-denial`, `fault.live-lock`, and the four builder fixtures |
| Store readers | version one, version two |
| Fast suite | 2 002 passed, 9 skipped |

`migration_red`: the adapter symmetry rule found a launch record whose field was named
`environment`; the parity found the older script raises after printing, so its report is
read from the output. `golden_change`: none. `supersedes`: a recorded entry supersedes the
imported document for the same check, by construction of the reader.

## P19d. Verification, fourth slice: the recovery and diagnostics probes

Goal: the four remaining probes that only read become units. Five commits on
`work/phase-19d-probes`, each green on the whole gate.

### A reserved file takes a mode

`FileSystemPort.reserve` takes the mode the file is created with, like every other write,
because a diagnostics capture on the operator's storage is private from its first byte. The
older collector created it exclusively; the unit reserves it, which is refused when the path
is taken, and then patches the bytes in, so an earlier capture is never overwritten.

### Four probes as units

`recovery.prerequisites` is `guest/recovery-probe.py`: the same eight programs and four
files, and the same reading of the deployment status, where two distinct deployments are a
prerequisite and never a pass. `recovery.installed` is `guest/installed-recovery-probe.py`:
the booted deployment must be the expected candidate, else the guest is refused as not the
one asked about; the installed GRUB file must be exactly bootupd's assembly of the image's
fragments, kept as `agent/grubstatic.py`; the retry configuration must hash to the fixture
the host names and carry the one-retry preset; SELinux must enforce. A configuration that
differs is a report that says what differs, never a refusal, because the report is the
evidence.

`guest.diagnostics` is `guest/diagnostics.py` with the destination as its argument.
`installer.diagnostics` is `guest/installer-diagnostics.py` without its transport: the logs
are read only when they are regular files and bounded at the same size, the programs are
bounded the same way, and the bundle has the same shape; the framing under the host's token,
which the older script wrote to the serial port itself, is what the agent does for every
unit.

The parity harnesses compare the programs and files for the readers, the judgement over
eight mutations for the installed probe, the codec dumps for the laptop collector, and the
bundle the older receiver decodes from the older emitter against the unit's document.

### What this slice did not do

The desktop render and theme probes carry GTK programs that must be shipped into the guest
and run under the user's session; they go with the screenshot stage that judges them. The
installer faults and the fingerprint fixture test follow. No `just` recipe calls any of
these units.

### Result

| Item | Value |
|---|---|
| Package | 263 files, 17181 lines |
| Units | eleven: five probes, three faults, four builder fixtures |
| Probe cases | six |
| Fast suite | 2039 passed, 9 skipped |

`migration_red`: the installed probe's tests found the answering fake could not fail a
program, and its write assertion counted the fixture's own writes. `golden_change`: none.
`supersedes`: none yet.

## P19e. Verification, fifth slice: the installer's trust, exercised

Goal: the two faults that prove the installer refuses what it must, and the first verbatim
asset. Five commits on `work/phase-19e-faults`, each green on the whole gate.

### A safety artifact moves byte for byte

`guest/installer-preflight.py` is the program that runs before Anaconda, and it is not
rewritten. It is carried as `assets/verbatim/installer-preflight.py.verbatim`, a data file
in the wheel that nothing scans as code, and an architecture test holds it equal to the
older tree's file for as long as that tree exists. `trust/preflight.py` executes those bytes
as a module and exposes the three calls the product makes with the types the product uses:
the policy the trust contract implies, the proxy check that a policy accepts an image, and
the whole verification. Its `ValueError` is a refused contract and its `RuntimeError` a
rejected signature, which is what those exceptions mean in its source.

### The payload fault

`fault.installer-payload` is `guest/test-installer-fault.py`: the same guards over the
offline installer guest at its diagnostic target, the same six mutations each with a
byte-for-byte backup and refused twice in one boot, the same run of the production entry
point, and the same reading of what it left behind. The wrong-key case writes the policy the
verbatim program derives from the rewritten contract, so the real verifier is what refuses.
The parity compares the files each mutation leaves on both sides and the judgement over six
outcomes of the entry point.

### The trust fixture

`fault.installer-trust` is `guest/test-installer-trust.py` through the engine port: a scratch
image built and signed with a fixture key, copied under the policy the trust contract
implies, opened through the same proxy check the installer uses, and then a wrong key, a
wrong identity, no signature, a tampered signature, a tampered manifest and an unexpected
source each refused. A negative the engine accepts, or refuses for another reason, refuses
the whole run, with the trust context's own reasons. The fake engine learned to refuse a
copy under a named policy. The parity runs the older script and the unit over the real
engine adapter on one scripted process and compares every argument vector, normalised for
the run directory and identifier, and both reports' cases.

### What this slice did not do

The fingerprint fixture test runs inside a container of the built image and is fed sources
the host must fetch, since a guest never downloads; it goes with the next slice. The desktop
probes and `generated/os/` follow. No `just` recipe calls any of these units.

### Result

| Item | Value |
|---|---|
| Package | 270 files, 18010 lines |
| Units | thirteen: five probes, five faults, four builder fixtures, less the fingerprint test |
| Verbatim assets | one |
| Fast suite | 2 102 passed, 9 skipped |

`migration_red`: the trust unit first hashed its small files through the digest port, which
reads disk and so could not be tested in memory; the payload unit's test had the older
guard's program order wrong; pyright refused a proxy stub assigned onto a module and the
tests now substitute it through the fixture. `golden_change`: none. `supersedes`: none yet.

## P19f. Verification, sixth slice: the fingerprint test, fed by the host

Goal: the one fixture test the older tree could not run without downloading inside the
builder, as a unit whose every input the host delivers. Five commits on
`work/phase-19f-fingerprint`, built in order, the whole gate green at the head.

### The harness moves byte for byte

`guest/test-fingerprint.py` is the program that produced the recorded result of September 9:
six upstream fprintd cases and two of this project's, over a virtual device on a private
bus, run as the unprivileged builder because the harness refuses root. It is carried as
`assets/verbatim/test-fingerprint.py.verbatim`, the second verbatim asset, and held equal to
the older file by the same architecture test. `agent/fingerprintharness.py` wraps it: the
bytes, their digest, where they are placed for the builder user to read, the argument vector
that runs them, and the older host's judgement of the report, which is PASS only when all
eight cases ran, none skipped, and the harness exited clean.

### The downloads move to the host

`guest/fingerprint-tests.sh` fetched the upstream test files with curl inside the builder and
checked them against `config/fingerprint-tests.lock.json`. A guest never downloads, so
`model/pinnedfiles.py` types that lock, a set of relative names each pinned to a digest under
one https base; `config/fingerprintpins.py` reads it out of the checkout like the source lock;
and `trust/testsources.py` fetches each file through the download port against its pin into
the runtime root, laid out as the harness expects, with the reviewed lock beside them, so the
directory can be sent into the guest as it is. A file already held with the right digest is
not fetched again, and the lock is recorded only once every file held.

### The test as a unit

`fault.fingerprint-cleanup` is `guest/fingerprint-tests.sh` step for step, less the downloads:
the isolation guard; the delivered files inspected, digested and compared with the lock, and
anything unpinned refused, before any program runs; fprintd and libfprint named from a
read-only, networkless container of the target image, and refused unless there are exactly
two; the same two installed on the builder with the test dependencies; the installed pair
compared with the target's; the builder's packages listed; the harness placed and run as the
builder user in the work directory, under the deadline the older `timeout` gave it. The
report is judged as the older host judged it and carried whole; a harness the port could not
run blocks the verdict with the cause rather than failing the run. The parity runs the older
shell under bash with every program stood in for by a script that records its arguments and
answers from the same spec the unit's fakes answer from, then compares the argument vectors
once the work directory is normalised and the downloads set aside, the three package
listings both leave, and the judgement.

P19e's note had this test running inside a container of the built image. It runs on the
builder itself; the image is only asked which packages it carries.

### The builder is a guest

The catalogue puts `fingerprint.virtual-cleanup`, `signature.accept` and `signature.reject`
in the build environment, and a fault case could not stand there, because a case's
registration counted `build` among the places that are not a guest. The isolated builder is
a guest like any test machine, so a case may now stand in `build`; only a simulation and the
operator's machine are refused. `fault.installer-trust` moves from `build-container` to
`build`, which is what its checks require, and the test that holds the cases to the
catalogue says so.

### What this slice did not do

No recipe runs the fingerprint test end to end yet: the stages that lease the builder,
prepare its work directory, transfer the sources and the frozen image document, and fill
the `work` argument go with the machine context. The desktop probes and `generated/os/`
follow. No `just` recipe calls any of these units.

### Result

| Item | Value |
|---|---|
| Package | 276 files, 18593 lines |
| Units | seventeen: seven probes, six faults, four builder fixtures |
| Verbatim assets | two |
| Fast suite | 2 155 passed, 9 skipped |

`migration_red`: the rpm query format first carried a real newline where the older shell
passes a backslash and an `n`, which the parity caught; the check for a linked delivery
looked for the file through its link and had to inspect the entry first. `golden_change`:
none. `supersedes`: none yet.

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
just deadcode               # unused code at vulture confidence 80
just plans-freeze           # record every recipe's derived plan, once per change
just plans                  # check the frozen plans still match the derived ones
just agent-wheel <dir>      # build the agent as a wheel and print its digest
just readiness-shadow       # compare the new readiness fold with the old one
just verify-chain           # replay the attestation chain and name the first break
just readiness-table        # read the real store through the versioned reader
just readiness-table-strict # the same, withholding every imported result
just guard-shadow           # compare the repository rules with the guard they replace
just gate                   # the standing gate for the current phase
```
