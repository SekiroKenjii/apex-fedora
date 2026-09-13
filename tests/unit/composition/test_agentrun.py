"""Delivering the guest program and asking it for one unit, on fakes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from apex.adapters.fakes import fake_guestshell
from apex.composition import agentrun
from apex.config import defaults
from apex.kernel import errors, identifiers, refusals, safepaths
from apex.model import serialframe
from apex.ports import guestshell, portset

TOKEN = identifiers.Token("f" * 32)
UNIT = identifiers.ProbeId("guest.state")


@pytest.fixture
def root(tmp_path: Path) -> safepaths.RuntimeRoot:
    base = tmp_path / "runtime"
    base.mkdir(mode=0o700)
    (base / "builder_ed25519").write_bytes(b"")
    (base / "apex-agent.whl").write_bytes(b"not really a wheel")
    return safepaths.RuntimeRoot.adopt(base)


def target(root: safepaths.RuntimeRoot) -> guestshell.GuestTarget:
    return guestshell.GuestTarget(
        user=defaults.BUILDER_USER,
        port=defaults.BUILDER_SSH_PORT,
        key=safepaths.SafePath.regular_file(root.path / "builder_ed25519", within=root),
        known_hosts=root.child(defaults.KNOWN_HOSTS_NAME),
    )


def guest_of(ports: portset.HostPorts) -> fake_guestshell.ScriptedGuest:
    assert isinstance(ports.guest, fake_guestshell.ScriptedGuest)
    return ports.guest


def wheel(root: safepaths.RuntimeRoot) -> safepaths.SafePath:
    return safepaths.SafePath.regular_file(root.path / "apex-agent.whl", within=root)


def framed(document: dict[str, object]) -> bytes:
    lines = serialframe.encode(json.dumps(document).encode(), token=TOKEN)
    return b"\n".join(lines) + b"\n"


def test_delivery_sends_the_wheel_and_unpacks_it_with_the_interpreter(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    remote = safepaths.RemotePath("/var/tmp/apex-run")

    install = agentrun.deliver(ports, target(root), wheel=wheel(root), remote=remote)

    guest = guest_of(ports)
    assert [str(item.remote) for item in guest.sent] == ["/var/tmp/apex-run/apex-agent.whl"]
    assert [run.script.rendered() for run in guest.runs] == [
        "mkdir -p -m 700 /var/tmp/apex-run/agent && "
        "python3 -m zipfile -e /var/tmp/apex-run/apex-agent.whl /var/tmp/apex-run/agent/lib"
    ]
    assert str(install.library) == "/var/tmp/apex-run/agent/lib"
    assert install.digest == ports.digests.file(wheel(root))


def test_a_unit_is_asked_under_the_lock_and_its_framed_reply_is_decoded(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    install = agentrun.AgentInstall(
        directory=safepaths.RemotePath("/var/tmp/apex-run/agent"),
        digest=identifiers.Digest("a" * 64),
    )
    script = (
        "cd /var/tmp/apex-run/agent && sudo flock -n /run/apex-build.lock bash -c "
        "'env PYTHONPATH=/var/tmp/apex-run/agent/lib python3 -m apex.agent.main run "
        f"--framed {TOKEN}'"
    )
    guest_of(ports).expect(
        script,
        fake_guestshell.GuestReply(
            stdout=framed({"protocol": 1, "unit": "guest.state", "observations": {"x": 1}})
        ),
    )

    reply = agentrun.run_unit(
        ports, target(root), install, unit=UNIT, arguments={"depth": 2}, token=TOKEN
    )

    assert reply.unit == UNIT
    assert reply.observations == {"x": 1}
    sent = guest_of(ports).runs[-1]
    assert sent.stdin is not None
    request = json.loads(sent.stdin)
    assert request["unit"] == "guest.state"
    assert request["arguments"] == {"depth": 2}
    assert request["agent_digest"] == "a" * 64


def test_the_guest_s_refusal_arrives_as_a_refusal_with_its_words(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    install = agentrun.AgentInstall(
        directory=safepaths.RemotePath("/var/tmp/apex-run/agent"),
        digest=identifiers.Digest("a" * 64),
    )
    guest = guest_of(ports)
    guest.expect(
        _script(),
        fake_guestshell.GuestReply(exit_code=2, stderr=b"BLOCKED: agent.unit-unknown: nope"),
    )

    with pytest.raises(errors.Refusal) as raised:
        agentrun.run_unit(ports, target(root), install, unit=UNIT, arguments={}, token=TOKEN)

    assert raised.value.reason is refusals.RefusalReason.AGENT_REFUSED
    assert "agent.unit-unknown" in raised.value.subject


def test_a_reply_for_another_unit_is_refused(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    install = agentrun.AgentInstall(
        directory=safepaths.RemotePath("/var/tmp/apex-run/agent"),
        digest=identifiers.Digest("a" * 64),
    )
    guest_of(ports).expect(
        _script(),
        fake_guestshell.GuestReply(
            stdout=framed({"protocol": 1, "unit": "other.unit", "observations": {}})
        ),
    )

    with pytest.raises(errors.Refusal) as raised:
        agentrun.run_unit(ports, target(root), install, unit=UNIT, arguments={}, token=TOKEN)

    assert raised.value.reason is refusals.RefusalReason.REQUEST_MALFORMED


def test_a_reply_that_never_finishes_is_refused_not_acted_on(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    install = agentrun.AgentInstall(
        directory=safepaths.RemotePath("/var/tmp/apex-run/agent"),
        digest=identifiers.Digest("a" * 64),
    )
    guest_of(ports).expect(_script(), fake_guestshell.GuestReply(stdout=b"noise\n"))

    with pytest.raises(errors.Refusal) as raised:
        agentrun.run_unit(ports, target(root), install, unit=UNIT, arguments={}, token=TOKEN)

    assert raised.value.reason is refusals.RefusalReason.FRAME_INCOMPLETE


def _script() -> str:
    return (
        "cd /var/tmp/apex-run/agent && sudo flock -n /run/apex-build.lock bash -c "
        "'env PYTHONPATH=/var/tmp/apex-run/agent/lib python3 -m apex.agent.main run "
        f"--framed {TOKEN}'"
    )


def test_a_session_unit_is_asked_as_the_user_without_the_lock(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    install = agentrun.AgentInstall(
        directory=safepaths.RemotePath("/var/tmp/apex-run/agent"),
        digest=identifiers.Digest("a" * 64),
    )
    script = (
        "cd /var/tmp/apex-run/agent && "
        "env PYTHONPATH=/var/tmp/apex-run/agent/lib python3 -m apex.agent.main run "
        f"--framed {TOKEN}"
    )
    guest_of(ports).expect(
        script,
        fake_guestshell.GuestReply(
            stdout=framed({"protocol": 1, "unit": "guest.state", "observations": {"x": 2}})
        ),
    )

    reply = agentrun.run_unit(
        ports, target(root), install, unit=UNIT, arguments={}, token=TOKEN, privileged=False
    )

    assert reply.observations == {"x": 2}
    assert guest_of(ports).runs[-1].script.rendered() == script


def test_a_privileged_unit_with_a_password_has_sudo_read_it_from_the_first_line(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    from apex.kernel import secrets  # noqa: PLC0415

    guest = guest_of(ports)
    install = agentrun.AgentInstall(
        directory=safepaths.RemotePath("/var/tmp/apex-run/agent"),
        digest=identifiers.Digest("a" * 64),
    )
    guest.expect(
        "cd /var/tmp/apex-run/agent && sudo -k -S -p '' flock -n /run/apex-build.lock unshare "
        "--mount --propagation slave bash -c 'env PYTHONPATH=/var/tmp/apex-run/agent/lib python3 "
        f"-m apex.agent.main run --framed {TOKEN}'",
        fake_guestshell.GuestReply(
            stdout=framed({"protocol": 1, "unit": str(UNIT), "observations": {"ok": True}})
        ),
    )

    reply = agentrun.run_unit(
        ports, target(root), install, unit=UNIT, arguments={}, token=TOKEN,
        password=secrets.Secret("Ab-1_"), private_mounts=True,
    )

    assert reply.observations == {"ok": True}
    stdin = guest.runs[-1].stdin
    assert stdin is not None and stdin.startswith(b"Ab-1_\n{")
    assert json.loads(stdin.split(b"\n", 1)[1])["unit"] == str(UNIT)


def test_one_program_as_root_carries_the_password_and_nothing_else_on_stdin(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    from apex.kernel import secrets, timing  # noqa: PLC0415

    guest = guest_of(ports)
    guest.expect(
        "sudo -k -S -p '' systemctl reboot", fake_guestshell.GuestReply(exit_code=255)
    )

    completed = agentrun.as_root(
        ports, target(root), "systemctl", "reboot",
        password=secrets.Secret("Ab-1_"), deadline=timing.Deadline(timing.Elapsed(5)),
    )

    assert completed.exit_code == 255
    assert guest.runs[-1].stdin == b"Ab-1_\n"
