# Apex

Fedora 44 and GNOME 50 on bootc, developed for the ASUS M7400QC.

Apex is under development. It is not ready to replace a working installation.
The release gate stays closed until installation, recovery and hardware checks have evidence for the same image digest.

The repository contains a file-backed Fedora builder VM launcher, Mock RPM packaging,
an OCI build pipeline, disk and live artifact recipes, local Git guards and tests for the build tools.
The desktop preset uses Graphite, Papirus-Dark, Geist, Maple Mono NF and macos-genie with Dash to Dock.

## Start here

Read [Build](docs/BUILD.md), then [Testing](docs/TESTING.md).
Run commands from the repository root. `just` recipes wrap the `apex` command line,
run as `python -m apex.cli.main` under `uv`.

```sh
just hooks
just doctor
just builder-prepare
just builder-start
just build fedora
```

Builders run privileged tools inside the Fedora VM. The host runs unprivileged QEMU,
file downloads, SSH and Python. No command installs Apex onto the host or writes a USB.
Stop the builder before running a test VM.

## Installation blockers

- ALC294 audio needs reproduction and a driver or routing fix. A visible sink is not proof of sound.
- ELAN fingerprint enrollment fails. Claim cleanup must be tested after protocol errors and cancellation.
- NVIDIA modules, the CachyOS comparison profile and Secure Boot acceptance are not complete.
- VM installer, update failure, rollback and live disk-protection acceptance remain unproven.
- Rescue media and backup restoration require operator checks on physical hardware.

`just readiness` exits unsuccessfully while required evidence is absent. A successful
unit test or image build does not override this gate.

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Build and artifact handling](docs/BUILD.md)
- [Test protocol and evidence](docs/TESTING.md)
- [Reproving the imported evidence](docs/REPROVING.md)
- [Installer acceptance and current failures](docs/INSTALLER.md)
- [Boot diagnostics](docs/BOOT-DIAGNOSTICS.md)
- [Recovery, including first installation](docs/RECOVERY.md)
- [Known issues](docs/KNOWN-ISSUES.md)
- [Contribution and Git rules](CONTRIBUTING.md)
