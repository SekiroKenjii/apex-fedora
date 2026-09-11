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
just readiness-shadow       # compare the new readiness fold with the old one
just verify-chain           # replay the attestation chain and name the first break
just readiness-table        # read the real store through the versioned reader
just readiness-table-strict # the same, withholding every imported result
just guard-shadow           # compare the repository rules with the guard they replace
just gate                   # the standing gate for the current phase
```
