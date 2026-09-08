# Boot diagnostics

Keep the original journal, serial output, boot ID, image digest and VM command with
each observation. A successful login does not explain a warning emitted during boot
or shutdown. Do not add kernel parameters merely to hide a message.

## Three separate mechanisms

| Mechanism | What it checks | Evidence to keep |
|---|---|---|
| Kernel clocksource watchdog | Clock frequency and cross-CPU consistency | Kernel journal and selected/available clocksources |
| Watchdog device | Whether software continues feeding a hardware or emulated timer | Device identity, state, timeout and systemd watchdog settings |
| GRUB and greenboot | Boot attempts and userspace health of a deployment | GRUB environment, deployment entries and greenboot journal |

None of these observations alone demonstrates recovery from a broken deployment.

## Remote clocksource read timeout

The Q35 test VM has emitted `Watchdog remote CPU ... read timed out`. In upstream
Linux 7.1.13, the remote check waits for timestamp handoffs. Its single-node timeout
is 50 microseconds. The `WD_CPU_TIMEOUT` result logs once and retries on a later cycle;
that result does not itself mark the clocksource unstable. Frequency or inter-CPU
skew follows a different path that can mark it unstable.

See [clocksource.c at v7.1.13](https://github.com/gregkh/linux/blob/v7.1.13/kernel/time/clocksource.c).
This identifies the upstream message path, not a confirmed cause in the Fedora guest.
Host scheduling delay is a possible explanation in a VM. It still needs comparison
with guest clocksource state, host load and repeated boots. Do not conclude that the
physical laptop has a faulty clock or disable the check from this message alone.

## Watchdog did not stop

The same VM exposes an emulated ICH9 TCO watchdog. During reboot it has emitted
`watchdog did not stop`. In upstream Linux 7.1.13, closing the watchdog file can print
this when the stop path fails or when a required magic-close character was not sent.
The core then feeds the timer. The text alone cannot distinguish those cases.

See [watchdog_release in watchdog_dev.c](https://github.com/gregkh/linux/blob/v7.1.13/drivers/watchdog/watchdog_dev.c).
Capture the device's `identity`, `state`, `nowayout` and `timeout` through sysfs, plus
systemd's runtime and reboot watchdog settings. Reading these attributes does not
open `/dev/watchdog` or start its timer. Do not probe by opening that device casually.

The ten-boot Fedora guest used kvm-clock, showed no clocksource-unstable message and
had the TCO timer inactive while the desktop ran. Its systemd settings were runtime
watchdog disabled and reboot watchdog at ten minutes. The installed systemd 259.8
[shutdown path](https://github.com/systemd/systemd/blob/v259.8/src/shutdown/shutdown.c)
explicitly closes the watchdog without disarming it to guard the remaining shutdown.
That is consistent with the observed reboot message. It does not prove timer expiry
or recovery from a hung guest.

The VM runner collects these values on every tested boot. Reboot completion, timer
behavior during a simulated hang and GRUB fallback still need separate tests. Keep
`boot.log-review` blocked until the remaining observations have a documented scope
and recovery results support that conclusion.
