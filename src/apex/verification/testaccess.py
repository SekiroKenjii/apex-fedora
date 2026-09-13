"""The disposable account's credentials, read from the runtime root and never rendered.

The older tool generated them beside the private fixture and read the password back at
login; the same file is read here, checked for shape, and the password is held as a secret
that reveals itself only into a sink, so no observation, proof or refusal can carry it.
"""

from __future__ import annotations

import dataclasses
import json

from apex.config import defaults
from apex.kernel import errors, refusals, safepaths, secrets
from apex.ports import files

USER = "user"
PASSWORD = "password"


@dataclasses.dataclass(frozen=True, slots=True)
class Credentials:
    user: str
    password: secrets.Secret[str]


def read(filesystem: files.FileSystemPort, path: safepaths.SafePath) -> Credentials:
    try:
        loaded = json.loads(filesystem.read_bytes(path, limit=defaults.DOCUMENT_LIMIT.value))
    except json.JSONDecodeError as error:
        raise _malformed(path, error.msg) from error
    if not isinstance(loaded, dict):
        raise _malformed(path, "not an object")
    user, password = loaded.get(USER), loaded.get(PASSWORD)
    if not isinstance(user, str) or not user or not isinstance(password, str) or not password:
        raise _malformed(path, f"{USER} and {PASSWORD} must be non-empty strings")
    return Credentials(user=user, password=secrets.Secret(password))


def _malformed(path: safepaths.SafePath, detail: str) -> errors.Refusal:
    return errors.Refusal(
        refusals.RefusalReason.CREDENTIALS_MALFORMED,
        subject=f"{path.path.name}: {detail}",
        remedy="generate the fixture's credentials again",
    )
