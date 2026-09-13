"""The disposable account's credentials, read from the runtime root and never rendered.

The older tool generated them beside the private fixture and read the password back at
login; the same file is read here, checked for shape, and the password is held as a secret
that reveals itself only into a sink, so no observation, proof or refusal can carry it. The
key the file names, when it names one, is the account's shell key.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

from apex.config import defaults
from apex.kernel import errors, refusals, safepaths, secrets
from apex.ports import files

USER = "user"
PASSWORD = "password"
KEY = "key"


@dataclasses.dataclass(frozen=True, slots=True)
class Credentials:
    user: str
    password: secrets.Secret[str]
    key: Path | None = None


def read(filesystem: files.FileSystemPort, path: safepaths.SafePath) -> Credentials:
    try:
        loaded = json.loads(filesystem.read_bytes(path, limit=defaults.DOCUMENT_LIMIT.value))
    except json.JSONDecodeError as error:
        raise _malformed(path, error.msg) from error
    if not isinstance(loaded, dict):
        raise _malformed(path, "not an object")
    user, password, key = loaded.get(USER), loaded.get(PASSWORD), loaded.get(KEY)
    if not isinstance(user, str) or not user or not isinstance(password, str) or not password:
        raise _malformed(path, f"{USER} and {PASSWORD} must be non-empty strings")
    if key is not None and (not isinstance(key, str) or not key):
        raise _malformed(path, f"{KEY} must name a file when present")
    return Credentials(
        user=user, password=secrets.Secret(password), key=None if key is None else Path(key)
    )


def _malformed(path: safepaths.SafePath, detail: str) -> errors.Refusal:
    return errors.Refusal(
        refusals.RefusalReason.CREDENTIALS_MALFORMED,
        subject=f"{path.path.name}: {detail}",
        remedy="generate the fixture's credentials again",
    )
