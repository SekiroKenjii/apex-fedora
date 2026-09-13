"""The guest's screen and keyboard through the hypervisor's monitor, for the desktop checks.

A capture is written by the hypervisor to a path the host names inside its runtime root and
read back through the file port, so the bytes filed as proof are the bytes on disk. A key
press is the sequence of key codes the older tool sent, held for the same time. Text is
typed one character at a time on the US layout the older console mapped, and a secret is
typed the same way through the one sink it reaches, mapped whole before the first key goes.
"""

from __future__ import annotations

from apex.composition import exports
from apex.config import defaults
from apex.kernel import errors, identifiers, refusals, safepaths, secrets
from apex.ports import portset, qmp

SCREENDUMP = "screendump"
SEND_KEY = "send-key"
PNG_SUFFIX = ".png"
PNG = "png"
QCODE = "qcode"
SHIFT = "shift"
PLAIN_KEYS = {
    " ": "spc", "\n": "ret", "\t": "tab", "-": "minus", "=": "equal", "[": "bracket_left",
    "]": "bracket_right", "\\": "backslash", ";": "semicolon", "'": "apostrophe", ",": "comma",
    ".": "dot", "/": "slash", "`": "grave_accent",
}
SHIFTED_KEYS = dict(zip("!@#$%^&*()", "1234567890", strict=True)) | {
    "_": "minus", "+": "equal", "{": "bracket_left", "}": "bracket_right", "|": "backslash",
    ":": "semicolon", '"': "apostrophe", "<": "comma", ">": "dot", "?": "slash",
    "~": "grave_accent",
}


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


def chord(character: str) -> tuple[str, ...]:
    """The key codes one character is typed with on the US layout, as the older console mapped."""
    if len(character) == 1 and character.isascii() and character.isalnum():
        return (SHIFT, character.lower()) if character.isupper() else (character,)
    if character in PLAIN_KEYS:
        return (PLAIN_KEYS[character],)
    if character in SHIFTED_KEYS:
        return (SHIFT, SHIFTED_KEYS[character])
    raise errors.Refusal(
        refusals.RefusalReason.CONSOLE_TEXT_UNSUPPORTED,
        subject="a character the US layout cannot type",
        remedy="use printable ASCII; transfer other text over the guest shell",
    )


def chords(text: str) -> tuple[tuple[str, ...], ...]:
    """Every character mapped before the first key is sent, so a bad one refuses the whole."""
    return tuple(chord(character) for character in text)


class _Typist:
    """The one sink a secret reaches: each character pressed as its chord, then forgotten."""

    def __init__(self, ports: portset.HostPorts, monitor: safepaths.SafePath) -> None:
        self._ports = ports
        self._monitor = monitor

    def accept(self, material: str) -> None:
        for keys in chords(material):
            press(self._ports, self._monitor, *keys)
            self._ports.clock.sleep(defaults.KEY_INTERVAL)


class _Mapper:
    """A sink that only maps, so a secret is refused before any key goes to the guest."""

    def accept(self, material: str) -> None:
        chords(material)


def typeable(secret: secrets.Secret[str]) -> None:
    secret.reveal_into(_Mapper())


def type_secret(
    ports: portset.HostPorts, monitor: safepaths.SafePath, secret: secrets.Secret[str]
) -> None:
    secret.reveal_into(_Typist(ports, monitor))


def capture_into(
    root: safepaths.RuntimeRoot, run: identifiers.RunId, name: str
) -> safepaths.SafePath:
    """Where a run keeps a named capture: under its own export directory, never elsewhere."""
    return exports.inside(root, run, f"{defaults.SCREENS_DIRECTORY}/{name}")
