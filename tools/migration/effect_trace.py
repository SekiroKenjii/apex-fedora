#!/usr/bin/env python3
"""Record the side effects a command performs, using the interpreter audit hook.

A refusal that touches nothing is a property worth pinning: the restructure must not
turn a clean refusal into one that has already taken a lock or written a file. The hook
observes the real interpreter, so no change to the code under test is needed.
"""

from __future__ import annotations

import json
import os
import runpy
import sys
from pathlib import Path

WATCHED = {
    "subprocess.Popen": "spawn",
    "open": "open",
    "os.rename": "rename",
    "os.remove": "remove",
    "os.mkdir": "mkdir",
    "shutil.copyfile": "copy",
    "socket.connect": "connect",
}
WRITE_MODES = frozenset("wxa+")
WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT


def _opens_for_writing(arguments: tuple[object, ...]) -> bool:
    mode = arguments[1] if len(arguments) > 1 else None
    if isinstance(mode, str):
        return bool(set(mode) & WRITE_MODES)
    flags = arguments[2] if len(arguments) > 2 else 0
    return isinstance(flags, int) and bool(flags & WRITE_FLAGS)


def install(events: list[dict[str, object]], root: str, repository: str) -> None:
    def redact(value: object) -> object:
        text = str(value)
        return text.replace(root, "<root>").replace(repository, "<repo>")

    def hook(event: str, arguments: tuple[object, ...]) -> None:
        kind = WATCHED.get(event)
        if kind is None:
            return
        if event == "open":
            if not _opens_for_writing(arguments):
                return
            events.append({"kind": "write", "target": redact(arguments[0])})
            return
        if event == "subprocess.Popen":
            raw = arguments[1] if len(arguments) > 1 else None
            argv = [redact(item) for item in (raw if isinstance(raw, list | tuple) else [])]
            events.append({"kind": "spawn", "argv": argv})
            return
        events.append({"kind": kind, "target": redact(arguments[0])})

    sys.addaudithook(hook)


def main() -> int:
    destination = Path(os.environ["APEX_EFFECT_TRACE"])
    root = os.environ.get("APEX_STATE_DIR", "")
    repository = str(Path(__file__).resolve().parents[2])
    events: list[dict[str, object]] = []
    install(events, root, repository)
    target = Path(sys.argv[1]).resolve()
    sys.path.insert(0, str(target.parent))
    sys.argv = sys.argv[1:]
    code = 0
    failure: str | None = None
    try:
        runpy.run_path(str(target), run_name="__main__")
    except SystemExit as exit_request:
        code = int(exit_request.code or 0)
    except BaseException as error:
        code = 70
        failure = type(error).__name__
    document: dict[str, object] = {"exit_code": code, "events": events}
    if failure is not None:
        document["uncaught"] = failure
    destination.write_text(json.dumps(document, indent=1) + "\n")
    return code


if __name__ == "__main__":
    sys.exit(main())
