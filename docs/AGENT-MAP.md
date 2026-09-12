# Agent map

Every program under `guest/` and the live root runs inside a builder, a test guest or the
live laptop. This table says what each one is for and where it goes as the agent, `apex.agent`,
under `src/apex/agent/` takes the work over. A row marked verbatim is a safety artifact that
moves byte for byte and is wrapped in types afterwards; it is never rewritten in place.

The agent is one wheel, `apex-agent`, with one unit per file under
`src/apex/agent/units/`. A unit runs against the guest's own ports and answers a versioned
request. The first unit, `guest.state`, replaces `guest/probe.py`; the others arrive with the
context that drives them.

| File | Lines | Role | Destination | Phase |
|---|---|---|---|---|
| `guest/probe.py` | 22 | probe | `guest.state` unit | P16, done |
| `guest/live-probe.py` | 97 | probe | `live.observe` unit over one sysfs snapshot; the older script stays until `just live-check` is repointed | P19a, done |
| `guest/live-usb-probe.py` | 75 | probe | `fault.usb-write-denial` unit over the sysfs snapshot and the block device port; the older script stays until `just test-live-check` is repointed | P19b, done |
| `guest/ventoy-probe.py` | 49 | probe | `ventoy.observe` unit over the same snapshot; the older script stays until `just live-check` is repointed | P19a, done |
| `guest/recovery-probe.py` | 68 | probe | `recovery.prerequisites` unit; the older script stays until `just recovery-probe` is repointed | P19d, done |
| `guest/installed-recovery-probe.py` | 58 | probe | `recovery.installed` unit with `agent/grubstatic.py`; the older script stays until its caller is repointed | P19d, done |
| `guest/render-probe.py` | 37 | probe, GTK | `assets/verbatim/render-probe.py.verbatim`, byte for byte, held equal by a test; placed and started by the `desktop.render` unit as the session's user, host case in `verification/probes/desktop_render_probe.py`; the older program stays until `tools/apexlib/guesttest.py` is repointed | verbatim, P19g, done |
| `guest/theme-probe.py` | 54 | probe, GTK | `assets/verbatim/theme-probe.py.verbatim`, byte for byte, held equal by a test; shown and stopped by the `desktop.theme-gtk3` and `desktop.theme-adwaita` units, the session's settings read by `desktop.theme-settings`; host cases under `verification/probes/`; the older program stays until `tools/apexlib/guesttest.py` is repointed | verbatim, P19g, done |
| `guest/diagnostics.py` | 40 | diagnostics | `guest.diagnostics` unit, the destination created exclusively through the file port; the older script stays for the operator's USB until the agent reaches the laptop | P19d, done |
| `guest/installer-diagnostics.py` | 89 | diagnostics, framed serial | `installer.diagnostics` unit; the framing is the agent's, under the host's token; the older script stays until `just installer-logs` is repointed | P19d, done |
| `guest/nvidia-check.py` | 56 | build check | `build.nvidia-check` unit | P18 |
| `guest/verify-image.py` | 57 | build check | `build.verify-image` unit | P18 |
| `guest/live-parity.py` | 19 | build check | `build.live-parity` unit | P18 |
| `guest/live-write-denial.py` | 124 | fault | `fault.live-write-denial` unit, host case in `verification/faults/live_write_denial_fault.py`; the older script stays until `just test-live-check` is repointed | P19b, done |
| `guest/live-lock-fault.py` | 103 | fault | `fault.live-lock` unit, its child run through the process port with `CAP_SYS_ADMIN` dropped; host case in `verification/faults/live_lock_fault.py`; the older script stays until `just test-live-check` is repointed | P19c, done |
| `guest/test-installer-fault.py` | 155 | fault | `fault.installer-payload` unit, host case in `verification/faults/installer_payload_fault.py`; the older script stays until `just test-installer-fault` is repointed | P19e, done |
| `guest/test-installer-trust.py` | 164 | fault, signatures | `fault.installer-trust` unit through the engine port, host case in `verification/faults/installer_trust_fault.py`; the older script stays until `just installer-trust` is repointed | P19e, done |
| `guest/test-fingerprint.py` | 108 | fixture test, harness | `assets/verbatim/test-fingerprint.py.verbatim`, byte for byte, held equal by a test; typed wrapper `agent/fingerprintharness.py`; run as the builder user by the `fault.fingerprint-cleanup` unit; the older script stays until `just test-fingerprint` is repointed | verbatim, P19f, done |
| `guest/initramfs-fixture.py` | 260 | fixture | host side in `provisioning/fixtures/initramfs_fixture.py`; guest steps become the `fixture.initramfs` unit | P17 host side done, P18c unit |
| `guest/recovery-fixture.py` | 182 | fixture | host side in `provisioning/fixtures/recovery_fixture.py`; guest steps become the `fixture.recovery` unit | P17 host side done, P18c unit |
| `guest/update-fixture.py` | 188 | fixture, signing | `fixture.update` unit on the container engine, host side in `provisioning/fixtures/update_fixture.py`; the older script stays until `just update-fixture` is repointed | P18c, done |
| `guest/installer-fixtures.py` | 88 | fixture | `fixture.installer-disks` unit, host side in `provisioning/fixtures/installer_fixture.py`; the older script stays until `just installer-fixtures` is repointed | P18b, done |
| `guest/ventoy-fixture.py` | 114 | fixture | `fixture.ventoy` unit, host side in `provisioning/fixtures/ventoy_fixture.py`; the older script stays until `just ventoy-fixture` is repointed | P18c, done |
| `guest/dedupe-update-blobs.py` | 153 | fixture, storage | `fixture.dedupe` unit over the extent port, layout in `model/extents.py`; the older script stays until `just dedupe` is repointed | P18c, done |
| `guest/nvidia-build.py` | 190 | build step | `composition/recipes/nvidia_recipe.py` guest side | P18 |
| `guest/fingerprint-rpms.py` | 137 | build step | `composition/recipes/fingerprint_rpms_recipe.py` guest side | P18 |
| `guest/fingerprint-rpm-smoke.py` | 66 | build check | `build.fingerprint-smoke` unit | P18 |
| `guest/fingerprint-image.py` | 150 | build step | `composition/recipes/fingerprint_image_recipe.py` guest side | P18 |
| `guest/fingerprint-gtk.py` | 163 | build test, GTK | `fingerprint.gtk` unit | P18 |
| `guest/fingerprint-gtk-service.py` | 166 | build test, D-Bus | support module of `fingerprint.gtk` | P18 |
| `guest/fetch-sources.py` | 16 | build step | retired; `trust/acquiring.py` on the host | P18 |
| `guest/sign-artifacts.py` | 35 | build step, signing | `build.sign-artifacts` unit on `SigningPort` | P18 |
| `guest/sign-installer-payload.py` | 77 | build step, signing | `build.sign-installer` unit on `SigningPort` | P18 |
| `guest/clean-image.py` | 34 | image step | `generated/os/` build step | P19 |
| `guest/compose-shell-theme.py` | 63 | image step | `generated/os/` build step | P19 |
| `guest/fix-grub-fragment.py` | 24 | image step | `generated/os/` build step | P19 |
| `guest/fix-schema-overrides.py` | 31 | image step | `generated/os/` build step | P19 |
| `guest/label-installer-manifest.py` | 66 | image step | `generated/os/` build step | P19 |
| `guest/guard-installer-entrypoint.py` | 37 | image step | `generated/os/` build step | P19 |
| `guest/prepare-live-builder.py` | 42 | image step | `generated/os/` build step | P19 |
| `guest/prepare-live-rootfs.py` | 132 | image step | `generated/os/` build step | P19 |
| `guest/installer-preflight.py` | 185 | safety artifact | `assets/verbatim/installer-preflight.py.verbatim`, byte for byte, held equal by a test; typed wrapper `trust/preflight.py` | verbatim, P19e, done |
| `guest/bootstrap.sh` | 13 | build shell | runs as shipped, first step under the guest lock in `composition/stages/run_build_stage.py` | P18 host side done |
| `guest/build.sh` | 35 | build shell | runs as shipped from `composition/recipes/image_recipe.py`; its steps become units when the builder carries the agent | P18 host side done |
| `guest/build-rpms.sh` | 19 | build shell | called by `build.sh` as shipped; a recipe of its own when the builder carries the agent | P18 host side done |
| `guest/disk-artifact.sh` | 84 | build shell | runs as shipped from `composition/recipes/disk_artifact_recipe.py` | P18 host side done |
| `guest/live-artifact.sh` | 35 | build shell | runs as shipped from `composition/recipes/live_artifact_recipe.py` | P18 host side done |
| `guest/import-payload.sh` | 20 | build shell | runs as shipped, first derived step in `run_build_stage.py` | P18 host side done |
| `guest/image-configure.sh` | 52 | image shell | `generated/os/` build step | P19 |
| `guest/installer-configure.sh` | 72 | image shell | `generated/os/` build step | P19 |
| `guest/assemble-live-squashfs.sh` | 22 | image shell | `generated/os/` build step | P19 |
| `guest/run-installer-osbuild.sh` | 18 | build shell | `composition` stage | P18 |
| `guest/fingerprint-tests.sh` | 25 | build shell | `fault.fingerprint-cleanup` unit step for step, host case in `verification/faults/fingerprint_cleanup_fault.py`; its downloads moved to the host, `trust/testsources.py` against `config/fingerprint-tests.lock.json`; the older script stays until `just test-fingerprint` is repointed | P19f, done |
| `live/rootfs/usr/libexec/apex/live-disk-guard.sh` | 40 | safety artifact | stays in the live root; tested unmodified | verbatim, done |
| `live/rootfs/usr/libexec/apex/live-protection-check.sh` | 7 | safety artifact | stays in the live root | verbatim |
| `live/rootfs/usr/lib/dracut/modules.d/01apexprotect/` | 13 | safety artifact | stays in the live root | verbatim |

## What a fixture's host side is

A fixture is made or mutated inside a builder or a disposable guest, and the steps that run
there belong to the agent. The host side, under `provisioning/fixtures/`, is everything that
can be decided without a guest: the request a builder is handed, the parser for the report it
sends back, the derivations the older scripts made in pure functions, and the refusals that
keep a fixture from passing as a release artifact. Each host-side module is checked against
the older script's pure functions in `tests/contract/test_fixture_parity.py`.

## How the host reaches a unit

`composition/agentrun.py` sends the wheel to the guest's run directory, unpacks it with the
interpreter's own archive module so the guest needs nothing installed, and asks for one unit
as root under the guest's build lock. The request names the wheel's digest; the reply comes
back framed under a token the host chose and is decoded by the shared codec in
`model/serialframe.py`. A refusal inside the guest arrives as a refusal on the host with the
guest's words.

## How a unit gets there

A unit is written against `AgentPorts` and the request shape in `model/agentwire.py`, with a
test on fakes that pins the observations it makes and the shape it answers. The older script
stays until the host side that calls it has moved, so the two exist beside each other for a
while and the parity test is what ties them. The older script is deleted in the same change
that repoints its caller, never earlier.

## What the wheel proves

`just agent-wheel <dir>` builds the wheel and prints its digest. The contract suite installs it
into a fresh environment and runs the handshake and the state unit from there, so discovery of
units inside site-packages, the console script and the protocol refusal are all exercised
before a wheel is ever copied into a guest.
