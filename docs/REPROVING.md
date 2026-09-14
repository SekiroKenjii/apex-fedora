# Reproving the imported evidence

The evidence store was written by the older tree until the cutover. Its records are read as
imported: each carries the permanent limits `legacy-no-port-proof` and
`legacy-no-candidate-readback`, `just readiness-table` shows them under `imported`, and
`just readiness-table-strict` withholds every pass among them. An imported record is
replaced when the same check is recorded again through the real ports: the new entry goes
onto the chain, the readiness fold reads the chain's latest entry for the check, and the
imported document stays where it is, superseded. Nothing deletes it.

This page names, for every imported check, the command that records it again and what the
command needs. A command that mints reads the selected candidate from `candidate.json` and
refuses a run whose bundle has a fake anywhere in it; the record's environment is what the
adapter that ran the check declared, never an argument.

## On the host, with no machine

`apex prove` records checks the host can establish on its own.

```sh
just prove-git                       # git.commit-policy, git.private-stage, git.outgoing-history
just prove-signature BUILD_ID KEY    # signature.accept, signature.reject
```

`prove git` makes three repositories under `runtime/git-proofs/<run>/`, each with a fixture
identity and none of the operator's Git configuration, and asks the hooks the questions
each check states: seven messages for the commit-msg hook, seven staged entries for the
pre-commit hook, four updates for the pre-push hook. The proof is one report per check with
every question, the rules it had to name and the rules the hook named. A hook that permits
everything, or refuses instead of answering, fails the record and the command.

`prove signature` verifies the build's signed output against a key supplied from outside it,
records `signature.accept` with the verification document, then runs every registered
negative over a scratch copy under `runtime/signature-tests/<run>/` and records
`signature.reject` with the results. The build must be the selected candidate's; another
build is refused before anything is recorded, because a record that cites another build
blocks readiness.

## In a machine, minted by the recipe

These recipes record their check themselves when the run completes.

| Check | Command |
|---|---|
| `desktop.password-wayland` | `just verify-desktop-render CREDENTIALS` |
| `desktop.theme-surfaces` | `just verify-desktop-theme USER` |
| `live.disk-protection` | `just verify-live-protection USER` |
| `fingerprint.virtual-cleanup` | `just test-fingerprint BUILD_ID` |

## In a machine, recorded by hand from the run's reports

These runs keep their reports under the run's exports and do not judge; the operator reads
the report, decides, and records with the report as proof.

```sh
apex record CHECK STATUS --environment vm --description TEXT --reason TEXT --proof FILE
```

| Check | Run | Proof |
|---|---|---|
| `live.direct` | `just test-live-check live-observe` on the ISO booted directly | the retained `live.observe` report |
| `live.ventoy` | `just test-live-check ventoy-observe` on the ISO booted through Ventoy | the retained `ventoy.observe` report |
| `installer.cancel` | `just test-installer ...`, quit before installation, `just test-compare-disks RUN` | the disk comparison record |
| `installer.offline` | `just test-installer ...` to completion, `just test-resume-installed RUN` | the run record and the resumed guest's state |
| `installer.other-disks` | `just test-installer ...` to completion, `just test-compare-disks RUN` | the disk comparison record |
| `installer.payload-rejection` | `just test-installer-fault CASE` for each case, `just test-installer-fault-collect RUN` | the collected results |
| `boot.ten-cycles` | ten `just test-vm DISK` boots of the frozen QCOW2 | the serial logs and the agent's state answers |
| `boot.log-review` | the journals and serial output of the boots above | the review |
| `boot.grub-counter` | the counter read across boots of the installed candidate | the GRUB environment as read |

## From a build, recorded by hand

| Check | Source | Proof |
|---|---|---|
| `image.lint` | the image build's `bootc container lint` step in the builder | the build's lint log |
| `rpm.dependencies` | the same build's `dnf5 check` over the container | the build's log and package list |
| `nvidia.kernel-match` | `just build-nvidia BUILD_ID`, whose report is bound to the image | the bound report and the image's package inventory |

## On the laptop

`audio.speakers` and `fingerprint.enroll` are physical checks. They are recorded on the
laptop with `apex record ... --environment physical`; a record of them from a machine is
refused.

## Not reprovable as written

`sources.locked` states that every build input is pinned. The reviewed lock pins the images
and the archives; RPM repository snapshots and buildroot locks are not pinned, which is why
the imported record is BLOCKED. No command mints it until the lock carries them.

## What a reproof does not do

Recording a check again does not change its scope. The catalogue's summary and limits say
what the check establishes; the record says that it was run, where, and with what proof.
