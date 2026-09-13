"""An ssh key pair made by the host's own tool, and its public half read back."""

from __future__ import annotations

from apex.config import defaults
from apex.kernel import commands, errors, safepaths
from apex.ports import portset

KEYGEN = "ssh-keygen"


def generate(ports: portset.HostPorts, key: safepaths.SafePath, *, comment: str) -> None:
    completed = ports.processes.run(
        commands.Argv.of(
            KEYGEN, "-q", "-t", defaults.BUILDER_KEY_TYPE, "-N", "", "-C", comment, "-f", key
        ),
        deadline=defaults.KEYGEN_DEADLINE,
        limit=commands.OutputLimit.default(),
    )
    if not completed.succeeded:
        raise errors.PortFailure(
            port=KEYGEN, cause=completed.stderr.decode(errors="replace").strip()
        )


def public_half(ports: portset.HostPorts, key: safepaths.SafePath) -> str:
    """The public key beside the private one, as one line without its newline."""
    public = safepaths.SafePath(key.path.with_name(key.path.name + defaults.PUBLIC_KEY_SUFFIX))
    return ports.files.read_bytes(public, limit=defaults.DOCUMENT_LIMIT.value).decode().strip()
