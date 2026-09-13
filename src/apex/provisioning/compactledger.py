"""The compaction's report as it grows, written after every step so a stopped run explains."""

from __future__ import annotations

import dataclasses

from apex.config import defaults
from apex.kernel import commands, encoding, errors, refusals, safepaths
from apex.ports import portset


@dataclasses.dataclass(frozen=True, slots=True)
class Compacted:
    report: safepaths.SafePath
    status: str
    replacement: str
    projected_free: int

    def document(self) -> encoding.Document:
        return {
            "report": str(self.report),
            "status": self.status,
            "replacement": self.replacement,
            "projected_free": self.projected_free,
        }


class Ledger:
    def __init__(
        self, ports: portset.HostPorts, path: safepaths.SafePath, document: encoding.Document
    ) -> None:
        self._ports = ports
        self.path = path
        self.document: dict[str, encoding.JsonValue] = dict(document)
        self.document.setdefault("commands", [])
        self.save()

    def save(self) -> None:
        self._ports.files.write_atomic(
            self.path, encoding.readable(self.document).encode() + b"\n", mode=defaults.RECORD_MODE
        )

    def note(self, **fields: encoding.JsonValue) -> None:
        self.document.update(fields)
        self.save()

    def command(
        self, argv: commands.Argv, *, transcript: safepaths.SafePath | None = None
    ) -> bytes:
        """Run one image tool call under the compaction deadline, recorded before it is judged."""
        completed = self._ports.processes.run(
            argv,
            deadline=defaults.COMPACTION_DEADLINE,
            limit=commands.OutputLimit.default(),
            transcript=transcript,
        )
        recorded = self.document["commands"]
        if isinstance(recorded, list):
            recorded.append(
                {
                    "argv": list(argv),
                    "returncode": completed.exit_code,
                    "stdout": completed.stdout.decode(errors="replace"),
                    "stderr": completed.stderr.decode(errors="replace"),
                }
            )
        self.save()
        if not completed.succeeded:
            raise self.refuse(
                refusals.RefusalReason.COMPACTION_VALIDATION_FAILED,
                f"{argv.arguments[1]} exited with {completed.exit_code}; original retained",
            )
        return completed.stdout

    def refuse(self, reason: refusals.RefusalReason, detail: str) -> errors.Refusal:
        self.note(error=detail)
        return errors.Refusal(reason, subject=detail, remedy=f"inspect {self.path}")
