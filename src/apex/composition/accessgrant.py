"""The disposable account a private QCOW2 fixture carries, made on the host for the guest.

The older tool generated a key pair and a password beside the export and wrote the blueprint
the image builder reads: one account in the wheel group with the hashed password and the
public key, and the kernel argument that starts sshd. The same is made here through ports:
the password is a token from the identity port, hashed by openssl over its standard input so
it never stands on a command line, the key pair by ssh-keygen; the credentials file keeps the
password for the login test and the key's path for the shell, and both stay with the run.
"""

from __future__ import annotations

import dataclasses
import json

from apex.composition import exports
from apex.config import defaults
from apex.kernel import commands, encoding, errors, identifiers, safepaths
from apex.ports import portset
from apex.provisioning import sshkeys

HASH = commands.Argv.of("openssl", "passwd", "-6", "-stdin")
WHEEL = "wheel"


@dataclasses.dataclass(frozen=True, slots=True)
class Granted:
    directory: safepaths.SafePath
    credentials: safepaths.SafePath
    key: safepaths.SafePath
    blueprint: safepaths.SafePath

    def document(self) -> encoding.Document:
        return {
            "user": defaults.TEST_ACCOUNT,
            "credentials": str(self.credentials),
            "key": str(self.key),
            "blueprint": str(self.blueprint),
        }


def blueprint(*, hashed: str, public_key: str) -> bytes:
    """The image builder's blueprint for the account, as the older tool wrote it."""
    return "\n".join((
        "[[customizations.user]]",
        f'name = "{defaults.TEST_ACCOUNT}"',
        f'description = "{defaults.TEST_ACCOUNT_DESCRIPTION}"',
        f"password = {json.dumps(hashed)}",
        f"key = {json.dumps(public_key)}",
        f'groups = ["{WHEEL}"]',
        "",
        "[customizations.kernel]",
        f'append = "{defaults.TEST_KERNEL_APPEND}"',
        "",
    )).encode()


def grant(
    ports: portset.HostPorts, *, root: safepaths.RuntimeRoot, run: identifiers.RunId
) -> Granted:
    directory = exports.inside(root, run, defaults.TEST_ACCESS_DIRECTORY)
    ports.files.make_directory(directory, mode=safepaths.PRIVATE_DIRECTORY_MODE)
    key = directory / defaults.TEST_KEY_NAME
    sshkeys.generate(ports, key, comment=defaults.TEST_KEY_COMMENT)
    password = str(ports.identities.token())
    credentials = directory / defaults.CREDENTIALS_NAME
    ports.files.write_atomic(
        credentials,
        encoding.canonical({
            "user": defaults.TEST_ACCOUNT, "password": password, "key": str(key),
        }) + b"\n",
        mode=defaults.RECORD_MODE,
    )
    written = directory / defaults.TEST_BLUEPRINT_NAME
    ports.files.write_atomic(
        written,
        blueprint(hashed=_hashed(ports, password), public_key=sshkeys.public_half(ports, key)),
        mode=defaults.RECORD_MODE,
    )
    return Granted(directory=directory, credentials=credentials, key=key, blueprint=written)


def _hashed(ports: portset.HostPorts, password: str) -> str:
    completed = ports.processes.run(
        HASH,
        deadline=defaults.PASSWORD_HASH_DEADLINE,
        limit=commands.OutputLimit.default(),
        stdin=f"{password}\n".encode(),
    )
    hashed = completed.stdout.decode(errors="replace").strip()
    if not completed.succeeded or not hashed:
        raise errors.PortFailure(port=HASH.arguments[0], cause="the password could not be hashed")
    return hashed
