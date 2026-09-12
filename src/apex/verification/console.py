"""The guest's screen and keyboard through the hypervisor's monitor, for the desktop checks.

A capture is written by the hypervisor to a path the host names inside its runtime root and
read back through the file port, so the bytes filed as proof are the bytes on disk. A key
press is the sequence of key codes the older tool sent, held for the same time.
"""

from __future__ import annotations

from apex.composition import exports
from apex.config import defaults
from apex.kernel import identifiers, safepaths
from apex.ports import portset, qmp

SCREENDUMP = "screendump"
SEND_KEY = "send-key"
PNG_SUFFIX = ".png"
PNG = "png"
QCODE = "qcode"


def capture(
    ports: portset.HostPorts, monitor: safepaths.SafePath, *, into: safepaths.SafePath
) -> bytes:
    """Dump the display to `into`, as PNG when the name says so and as PPM otherwise."""
    arguments: dict[str, object] = {"filename": str(into)}
    if into.path.suffix == PNG_SUFFIX:
        arguments["format"] = PNG
    with ports.monitor.connect(monitor, deadline=defaults.QMP_DEADLINE) as session:
        session.execute(qmp.QmpCommand(SCREENDUMP, arguments))
    return ports.files.read_bytes(into, limit=defaults.SCREEN_LIMIT.value)


def press(ports: portset.HostPorts, monitor: safepaths.SafePath, *codes: str) -> None:
    """Send the key codes together, the way a chord is pressed, held briefly."""
    keys: list[object] = [{"type": QCODE, "data": code} for code in codes]
    with ports.monitor.connect(monitor, deadline=defaults.QMP_DEADLINE) as session:
        session.execute(
            qmp.QmpCommand(SEND_KEY, {"keys": keys, "hold-time": defaults.KEY_HOLD_MILLISECONDS})
        )


def capture_into(
    root: safepaths.RuntimeRoot, run: identifiers.RunId, name: str
) -> safepaths.SafePath:
    """Where a run keeps a named capture: under its own export directory, never elsewhere."""
    return exports.inside(root, run, f"{defaults.SCREENS_DIRECTORY}/{name}")
