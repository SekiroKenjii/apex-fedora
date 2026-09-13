"""A monitor that draws a declared frame wherever the host names a capture.

The host names each capture inside its runtime root and reads the bytes back through its
file port, so the fake writes the frame a test declared for that name through the same
port, and answers a key press with nothing, as the real monitor does.
"""

from __future__ import annotations

from pathlib import Path

from apex.adapters.fakes import fake_files, fake_qmp
from apex.config import defaults
from apex.kernel import safepaths
from apex.ports import qmp

PNG_BYTES = b"png bytes"


class DrawingMonitor(fake_qmp.ScriptedQmp):
    """Writes the frame declared for each capture's name; a name not declared gets PNG bytes."""

    def __init__(
        self, files: fake_files.MemoryFiles, frames: dict[str, bytes] | None = None
    ) -> None:
        super().__init__({"screendump": {}, "send-key": {}})
        self.frames = dict(frames or {})
        self.react_to("screendump", lambda command: self._draw(files, command))

    def _draw(self, files: fake_files.MemoryFiles, command: qmp.QmpCommand) -> None:
        path = Path(str(command.arguments["filename"]))
        files.write_atomic(
            safepaths.SafePath(path), self.frames.get(path.name, PNG_BYTES),
            mode=defaults.RECORD_MODE,
        )

    def captured(self) -> list[str]:
        """The names captured, in order."""
        return [
            Path(str(command.arguments["filename"])).name
            for command in self.executed
            if command.name == "screendump"
        ]

    def pressed(self) -> list[list[str]]:
        """The key codes of every press, in order."""
        return [
            [str(key["data"]) for key in command.arguments["keys"]]  # type: ignore[index,union-attr]
            for command in self.executed
            if command.name == "send-key"
        ]
