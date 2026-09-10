# Architecture

## Boundaries

Ubuntu is the development host. It lends CPU, RAM, a file-backed virtual disk and a
private OVMF variable store to one QEMU VM at a time. The VM receives no physical disk,
GPU, USB controller, audio device, host home directory or container socket.

The builder receives a source archive through SCP. Mock builds custom packages in
Fedora chroots. Podman builds the bootc image inside that VM. All artifacts return
through a separate export directory. Test VMs boot fresh QCOW2 overlays so failures
do not modify the source disk image.

## Image variants

| Variant | Intended use | Current restriction |
|---|---|---|
| Fedora kernel | Control image and initial integration | Not hardware-approved |
| CachyOS GCC | One-variable kernel comparison | Blocked pending reviewed source/RPM and NVIDIA lock |
| Live derivative | Physical diagnostics | Disk protection and boot acceptance required |

The initial hardware fixes must keep the baseline kernel configuration. A codec fix
does not justify dropping modules or changing the scheduler. Later optimization must
keep storage, encryption, USB, VM and rescue support that may not appear in `lsmod`.

NVIDIA will use render offload while AMD drives the internal panel. Kernel-matched
modules must be present before first boot. A driver package is not accepted merely
because its installation succeeds. Vermagic, firmware, module loading, HDMI and
runtime suspension require separate checks.

## Desktop and user state

Dconf provides defaults, without locking personal settings. The user service manages
a separate GTK CSS file and imports it before personal CSS. It updates only files
whose contents still match its ownership record. Existing unowned files and user
changes remain intact. This applies to existing users as well as new accounts.

GTK retains Adwaita-dark as its complete widget theme, with Graphite CSS applied through
the managed user files. The Shell override is combined with the installed GNOME Shell's
base resource during image creation. Selecting the override fragments as complete
themes can leave unstyled or transparent surfaces. The build records the base and
resulting stylesheet hashes; VM screenshots still need to confirm the result.
This follows the [upstream theme layering](https://github.com/SekiroKenjii/shadcn-gnome/blob/39d566801b07c7ef6af4377ef58904a019e9693b/install.sh#L170).
The composer reads the base bundle through [GIO resources](https://docs.gtk.org/gio/struct.Resource.html).

Flatpak theme access, offline app provisioning and the Lotus package remain separate
work. Do not grant all of the home directory to Flatpak for theme access. GNOME patches
and Apex Control are deferred until hardware and recovery pass. No unsupported control
should be exposed as if a working backend existed.

## Installed recovery

Greenboot-rs 0.16.4 is selected from Fedora packages. Apex installs an offline required
check for the mounted root, bootc state, system D-Bus, GDM and SELinux. It sets a two-attempt
limit and includes the GRUB integration supplied by greenboot. Audio, network and
fingerprint failures are not reboot triggers.

Configuration is not proof of recovery. The VM suite must establish counter behavior,
fallback selection and what happens with no known-good deployment. A hang before
userspace can require a person to power-cycle the machine.

See [greenboot-rs](https://github.com/fedora-iot/greenboot-rs) and the
[recovery procedure](RECOVERY.md). Automatic update application and reboot are disabled.
