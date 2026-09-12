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
| `guest/live-probe.py` | 97 | probe | `live.observe` unit | P19 |
| `guest/live-usb-probe.py` | 75 | probe | `live.usb-fixture` unit | P19 |
| `guest/ventoy-probe.py` | 49 | probe | `ventoy.observe` unit | P19 |
| `guest/recovery-probe.py` | 68 | probe | `recovery.prerequisites` unit | P19 |
| `guest/installed-recovery-probe.py` | 58 | probe | `recovery.installed` unit | P19 |
| `guest/render-probe.py` | 37 | probe, GTK | `desktop.render` unit | P19 |
| `guest/theme-probe.py` | 54 | probe, GTK | `desktop.theme` unit | P19 |
| `guest/diagnostics.py` | 40 | diagnostics | `guest.diagnostics` unit | P19 |
| `guest/installer-diagnostics.py` | 89 | diagnostics, framed serial | `installer.diagnostics` unit on the shared codec | P19 |
| `guest/nvidia-check.py` | 56 | build check | `build.nvidia-check` unit | P18 |
| `guest/verify-image.py` | 57 | build check | `build.verify-image` unit | P18 |
| `guest/live-parity.py` | 19 | build check | `build.live-parity` unit | P18 |
| `guest/live-write-denial.py` | 124 | fault | `verification/faults/live_write_denial_fault.py` | P19 |
| `guest/live-lock-fault.py` | 103 | fault | `verification/faults/live_lock_fault.py` | P19 |
| `guest/test-installer-fault.py` | 155 | fault | `verification/faults/installer_payload_fault.py` | P19 |
| `guest/test-installer-trust.py` | 164 | fault, signatures | `verification/faults/installer_trust_fault.py` | P19 |
| `guest/test-fingerprint.py` | 108 | fixture test | `fingerprint.virtual` unit | P19 |
| `guest/initramfs-fixture.py` | 260 | fixture | host side in `provisioning/fixtures/initramfs_fixture.py`; guest steps become the `fixture.initramfs` unit | P17 host side done, P18 unit |
| `guest/recovery-fixture.py` | 182 | fixture | host side in `provisioning/fixtures/recovery_fixture.py`; guest steps become the `fixture.recovery` unit | P17 host side done, P18 unit |
| `guest/update-fixture.py` | 188 | fixture, signing | host side in `provisioning/fixtures/update_fixture.py`; builder steps become the `fixture.update` unit on `ContainerEnginePort` | P17 host side done, P18 unit |
| `guest/installer-fixtures.py` | 88 | fixture | host side in `provisioning/fixtures/installer_fixture.py`; builder steps become the `fixture.installer-disks` unit | P17 host side done, P18 unit |
| `guest/ventoy-fixture.py` | 114 | fixture | host side in `provisioning/fixtures/ventoy_fixture.py`; builder steps become the `fixture.ventoy` unit | P17 host side done, P18 unit |
| `guest/dedupe-update-blobs.py` | 153 | fixture, storage | host side in `provisioning/fixtures/dedupe_fixture.py`; the ioctl runs in the `fixture.dedupe` unit | P17 host side done, P18 unit |
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
| `guest/installer-preflight.py` | 185 | safety artifact | `assets/verbatim/`, typed wrapper in `trust/` | verbatim, P19 |
| `guest/bootstrap.sh` | 13 | build shell | `composition` remote run | P18 |
| `guest/build.sh` | 35 | build shell | `composition/recipes/image_recipe.py` | P18 |
| `guest/build-rpms.sh` | 19 | build shell | `composition/recipes/rpms_recipe.py` | P18 |
| `guest/disk-artifact.sh` | 84 | build shell | `composition/recipes/disk_artifact_recipe.py` | P18 |
| `guest/live-artifact.sh` | 35 | build shell | `composition/recipes/live_artifact_recipe.py` | P18 |
| `guest/import-payload.sh` | 20 | build shell | `composition` stage | P18 |
| `guest/image-configure.sh` | 52 | image shell | `generated/os/` build step | P19 |
| `guest/installer-configure.sh` | 72 | image shell | `generated/os/` build step | P19 |
| `guest/assemble-live-squashfs.sh` | 22 | image shell | `generated/os/` build step | P19 |
| `guest/run-installer-osbuild.sh` | 18 | build shell | `composition` stage | P18 |
| `guest/fingerprint-tests.sh` | 25 | build shell | `composition` stage | P18 |
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

## How a unit gets there

A unit is written against `AgentPorts` and the request shape in `guest/requests.py`, with a
test on fakes that pins the observations it makes and the shape it answers. The older script
stays until the host side that calls it has moved, so the two exist beside each other for a
while and the parity test is what ties them. The older script is deleted in the same change
that repoints its caller, never earlier.

## What the wheel proves

`just agent-wheel <dir>` builds the wheel and prints its digest. The contract suite installs it
into a fresh environment and runs the handshake and the state unit from there, so discovery of
units inside site-packages, the console script and the protocol refusal are all exercised
before a wheel is ever copied into a guest.
