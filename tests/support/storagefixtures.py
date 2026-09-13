"""A process that answers the image and key tools and leaves behind what each would have made."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from apex.adapters.fakes import fake_process

PUBLIC_KEY = "ssh-ed25519 AAAA apex-local-builder"


class Storage(fake_process.ScriptedProcess):
    """qemu-img reports a standalone image and creates the overlay; ssh-keygen writes a pair.

    Given a backing name, every image but that one is reported as backed by it.
    """

    def __init__(self, *, backing: str | None = None, keygen_exit: int = 0) -> None:
        super().__init__()
        self.backing = backing
        self.keygen_exit = keygen_exit

    def run(self, argv: Any, **keywords: Any) -> Any:
        vector = tuple(str(item) for item in argv)
        if vector[:2] == ("qemu-img", "info"):
            info: dict[str, str] = {"format": "qcow2"}
            if self.backing is not None and Path(vector[-1]).name != self.backing:
                info["backing-filename"] = self.backing
            self.expect(vector, fake_process.Reply(stdout=json.dumps(info).encode()))
        elif vector[:2] == ("qemu-img", "create"):
            target = Path(vector[-2] if vector[-1].endswith("G") else vector[-1])
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"")
            self.expect(vector, fake_process.Reply())
        elif vector[:1] == ("ssh-keygen",):
            self._keygen(Path(vector[-1]))
            self.expect(vector, fake_process.Reply(exit_code=self.keygen_exit, stderr=b"keygen"))
        return super().run(argv, **keywords)

    def _keygen(self, key: Path) -> None:
        if self.keygen_exit != 0:
            return
        key.write_bytes(b"private key")
        key.with_name(key.name + ".pub").write_bytes(f"{PUBLIC_KEY}\n".encode())
