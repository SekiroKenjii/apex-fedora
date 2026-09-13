"""A serial guest shell that answers from a table, exactly as the scripted ssh guest does.

The serial adapter differs from the ssh one only in how the bytes travel, so the fake is
the scripted guest under the serial adapter's name, remembering which socket and which
process it was opened for.
"""

from __future__ import annotations

from apex.adapters.fakes import fake_guestshell
from apex.kernel import claims, safepaths


class ScriptedSerialShell(fake_guestshell.ScriptedGuest):
    environment = claims.EnvironmentKind.SIMULATED

    def __init__(self, socket_path: safepaths.SafePath, *, expected_process: int) -> None:
        super().__init__()
        self.socket_path = socket_path
        self.expected_process = expected_process
