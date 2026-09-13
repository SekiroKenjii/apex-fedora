"""A scripted guest that answers unit requests from a table, framed under the host's token.

The live protection and desktop recipes both drive the agent through the guest shell; this
stand-in reads the unit out of the request on stdin and answers with the observations the
test declared for it, so a recipe runs end to end on fakes.
"""

from __future__ import annotations

import json

from apex.adapters.fakes import fake_guestshell
from apex.kernel import commands, identifiers
from apex.model import agentwire, serialframe
from apex.ports import guestshell

Answer = dict[str, object]


class AnsweringGuest(fake_guestshell.ScriptedGuest):
    """Answers a unit request with the observations declared for that unit, framed.

    An answer is a document, or a list of documents given out in order for a unit that is
    asked more than once in a run. A request sent through sudo with a password on the first
    line has that line taken off and kept, so a test can see it was given and never shown.
    """

    def __init__(self, answers: dict[str, Answer | list[Answer]]) -> None:
        super().__init__()
        self.answers = answers
        self.asked: list[str] = []
        self.requests: list[dict[str, object]] = []
        self.passwords: list[str] = []

    def run(
        self, target: guestshell.GuestTarget, run: guestshell.GuestRun
    ) -> commands.CompletedRun:
        text = run.script.rendered()
        if "--framed" not in text or run.stdin is None:
            return super().run(target, run)
        self.runs.append(run)
        token = identifiers.Token(text.split("--framed ", 1)[1].split("'", 1)[0])
        payload = run.stdin
        if "sudo -k -S" in text:
            password, _, payload = payload.partition(b"\n")
            self.passwords.append(password.decode())
        request = json.loads(payload)
        unit = str(request["unit"])
        self.asked.append(unit)
        self.requests.append(request)
        if unit not in self.answers:
            return commands.CompletedRun(
                exit_code=2, stdout=b"", stderr=b"BLOCKED: agent.unit-unknown: " + unit.encode(),
                truncated=False,
            )
        answer = self.answers[unit]
        observations = answer.pop(0) if isinstance(answer, list) else answer
        document = {
            "protocol": agentwire.PROTOCOL_VERSION,
            "unit": unit,
            "observations": observations,
        }
        lines = serialframe.encode(json.dumps(document).encode(), token=token)
        return commands.CompletedRun(
            exit_code=0, stdout=b"\n".join(lines) + b"\n", stderr=b"", truncated=False
        )
