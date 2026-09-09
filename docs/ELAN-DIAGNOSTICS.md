# ELAN status diagnostics

The experimental patch `rpms/patches/libfprint-elan-status-diagnostics.patch` adds
metadata logging to the image-based ELAN driver. It has not been built into libfprint,
installed on Ubuntu or included in Apex. It does not change retries, calibration,
timeouts or error handling. The physical protocol failure remains unresolved.

## What the source establishes

Both audited versions have an explicit protocol-error return in CAPTURE_READ_DATA
after a pre-scan response other than the expected finger-present status. Fedora has
an additional retry for 0c58, which does not apply to this laptop's 0c6e. The same
capture path serves the identify-for-enroll and enrollment attempts seen in the logs.
The actual failing response is still unknown.

There are at least two cases worth distinguishing: an unexpected status byte and a
zero-length response. The reviewed USB helper's short-transfer check requires
`actual_length > 0`, so zero length is not rejected by that check. A positive short
read produces a G_USB_DEVICE_ERROR_IO error, not the driver's explicit protocol error.
This source behavior is a diagnostic lead, not evidence of a zero-length response on
the physical sensor.

Sources: [ELAN capture and transfer callbacks](https://gitlab.freedesktop.org/libfprint/libfprint/-/blob/v1.94.100/libfprint/drivers/elan.c),
[USB transfer completion](https://gitlab.freedesktop.org/libfprint/libfprint/-/blob/v1.94.100/libfprint/fpi-usb-transfer.c).

The Fedora `libfprint-1.94.100-1.fc44` source RPM has no downstream patches. Its ELAN
files match the reviewed upstream bytes. Ubuntu's `1:1.95.1+tod1-0ubuntu2` source has
different frame-processing code but its packaging does not patch elan.c/h. Input hashes
are in `config/elan-diagnostics.lock.json`. HTTPS/checksum checks are complete; source
signatures have not been independently validated. Record that trust limitation when
selecting build inputs.

## Logged fields and exclusions

The helper requires the exact opt-in `APEX_ELAN_STATUS_DIAGNOSTICS=1` and USB identity
04f3:0c6e. It refuses to log when FP_DEBUG_TRANSFER or G_MESSAGES_DEBUG is present,
even with an empty value. It emits at most sixteen records per device object, without
resetting that budget between captures.

Each `apex-elan-v1` record contains an event label, numeric action/state, a fixed command
category, expected/actual transfer lengths, status, and numeric error domain/code.
Domain categories are 0 for none, 1 for FP_DEVICE_ERROR, 2 for G_USB_DEVICE_ERROR,
3 for G_IO_ERROR and 4 for another domain. The protocol event has domain/code zero
because it is logged immediately before the existing protocol error is constructed.
Status is decimal; -1 means no eligible status byte was observed, not byte 0xff.

The only buffer read added by the patch requires all of these conditions:

- The command object is exactly pre_scan_cmd.
- The response endpoint is ELAN_EP_CMD_IN.
- Expected and actual lengths are both one, the transfer succeeded, and the buffer
  pointer is non-null.

Image and calibration buffers, failed or short transfers, and outgoing command bytes
are excluded. Error-message bodies, device serials, usernames, templates and image
statistics are not logged. A transfer error records metadata only. The protocol-error
branch records the saved pre-scan status without changing the driver's decision.

These guards control this helper only. They do not disable other libfprint logging.
Upstream FP_DEBUG_TRANSFER can dump complete buffers. A future trial runner must
reject broad debug and USB-recording settings before starting the daemon; it must not
rely on filtering sensitive payloads after they have already entered the journal.

## Tests and limits

With a prepared, checksum-matching elan.c and existing C/GIO development tools:

```sh
just test-elan-diagnostics /path/to/elan.c
```

The runner refuses root and an unknown source hash. It applies the patch without
fuzz, extracts its actual helper code and compiles it with fake transfer/device APIs.
Non-status buffers use an invalid address: an accidental read would crash the test.
A synthetic error-message marker must not appear in output. The twenty scenarios
cover opt-in/identity guards, excluded transfers, four status values and the event
budget. Every output line must match the fixed metadata format. Reversing the patch
must restore the original source hash.

All twenty scenarios passed for each audited source. This proves the helper's tested
read/logging boundaries, not the complete driver or capture state machine. Source
application and reversal also passed. No physical payload or fingerprint image was
used, and no enrollment was started by the tests.

Before a physical trial, build and test the complete patched libfprint in the dedicated
Fedora VM, then prepare a separately identified live candidate. Keep broad debug
logging disabled, use a bounded metadata capture and obtain operator approval for
that specific trial. Do not replace Ubuntu libraries or enable a diagnostic service
on the working installation. The builder is currently blocked by its storage checks;
there is no diagnostic live artifact ready to boot.
