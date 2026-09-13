"""The disposable account is made on the host: a key, a hashed password, the blueprint."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest

from apex.adapters.fakes import fake_files, fake_process
from apex.composition import accessgrant
from apex.kernel import errors, identifiers, safepaths
from apex.ports import portset

RUN = identifiers.RunId("a" * 32)
PUBLIC = "ssh-ed25519 AAAA apex-disposable-test"


class AccountTools(fake_process.ScriptedProcess):
    """ssh-keygen leaves a pair in the fake files; openssl hashes whatever it is fed."""

    def __init__(self, files: fake_files.MemoryFiles, *, hashing_exit: int = 0) -> None:
        super().__init__()
        self.files = files
        self.hashing_exit = hashing_exit
        self.fed: list[bytes | None] = []

    def run(self, argv: Any, **keywords: Any) -> Any:
        vector = tuple(str(item) for item in argv)
        if vector[:1] == ("ssh-keygen",):
            key = Path(vector[-1])
            mode = safepaths.PRIVATE_DIRECTORY_MODE
            self.files.write_atomic(safepaths.SafePath(key), b"private", mode=mode)
            self.files.write_atomic(
                safepaths.SafePath(key.with_name(key.name + ".pub")),
                f"{PUBLIC}\n".encode(),
                mode=mode,
            )
            self.expect(vector, fake_process.Reply())
        elif vector[:2] == ("openssl", "passwd"):
            self.fed.append(keywords.get("stdin"))
            fed = keywords.get("stdin") or b""
            self.expect(
                vector,
                fake_process.Reply(
                    exit_code=self.hashing_exit, stdout=b"$6$salt$" + fed.strip() + b"\n"
                ),
            )
        return super().run(argv, **keywords)


@pytest.fixture
def root(tmp_path: Path) -> safepaths.RuntimeRoot:
    base = tmp_path / "runtime"
    base.mkdir(mode=0o700)
    return safepaths.RuntimeRoot.adopt(base)


def bundle(ports: portset.HostPorts, **changes: Any) -> tuple[portset.HostPorts, AccountTools]:
    files = fake_files.MemoryFiles()
    tools = AccountTools(files, **changes)
    return dataclasses.replace(ports, files=files, processes=tools), tools


def test_the_account_is_granted_with_its_key_password_and_blueprint(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    held, tools = bundle(ports)

    granted = accessgrant.grant(held, root=root, run=RUN)

    directory = root.path / "exports" / str(RUN) / "test-access"
    assert granted.directory.path == directory
    assert granted.key.path == directory / "id_ed25519"
    credentials = json.loads(held.files.read_bytes(granted.credentials, limit=1 << 20))
    assert credentials["user"] == "apex-test" and credentials["key"] == str(granted.key)
    password = credentials["password"]
    assert len(password) == 32 and tools.fed == [f"{password}\n".encode()]
    blueprint = held.files.read_bytes(granted.blueprint, limit=1 << 20).decode()
    assert blueprint == (
        "[[customizations.user]]\n"
        'name = "apex-test"\n'
        'description = "Disposable Apex VM test account"\n'
        f'password = "$6$salt${password}"\n'
        f'key = "{PUBLIC}"\n'
        'groups = ["wheel"]\n'
        "\n"
        "[customizations.kernel]\n"
        'append = "systemd.wants=sshd.service"\n'
    )
    for path in (granted.credentials, granted.blueprint):
        assert held.files.mode_of(path).value == 0o600
    assert "ssh-keygen" in [call.arguments[0] for call in tools.calls]
    assert password not in " ".join(" ".join(call.arguments) for call in tools.calls)
    assert granted.document()["user"] == "apex-test"


def test_a_password_that_cannot_be_hashed_fails_the_port_before_the_blueprint(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    held, _ = bundle(ports, hashing_exit=1)

    with pytest.raises(errors.PortFailure) as caught:
        accessgrant.grant(held, root=root, run=RUN)

    assert caught.value.port == "openssl"
    assert not held.files.exists(root.child(f"exports/{RUN}/test-access/blueprint.toml"))
