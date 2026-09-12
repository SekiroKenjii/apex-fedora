"""Reaching a guest: the script arrives whole, files go both ways, and the target is typed.

The real adapter runs against ssh and scp stand-ins on the path, so the argument vectors and
the copy semantics are exercised without a guest. A guest that answers is the integration tier.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from apex.adapters.fakes import fake_guestshell
from apex.config import defaults
from apex.kernel import commands, errors, quantities, refusals, safepaths
from apex.ports import guestshell


def target(root: safepaths.RuntimeRoot) -> guestshell.GuestTarget:
    key = root.path / "builder_ed25519"
    key.write_bytes(b"")
    return guestshell.GuestTarget(
        user="builder",
        port=quantities.TcpPort(22244),
        key=safepaths.SafePath.regular_file(key, within=root),
        known_hosts=root.child("known_hosts"),
    )


def script() -> guestshell.RemoteScript:
    return guestshell.RemoteScript.of(
        guestshell.Step.of("cd", "/var/tmp/apex-run"),
        guestshell.Step.of("tar", "-xf", "source.tar"),
    )


def test_the_rendered_script_is_what_the_guest_receives(
    guests: guestshell.GuestShellPort, root: safepaths.RuntimeRoot
) -> None:
    completed = guests.run(
        target(root),
        guestshell.GuestRun(
            script=script(),
            deadline=defaults.GUEST_COMMAND_DEADLINE,
            limit=commands.OutputLimit.default(),
        ),
    )

    assert completed.succeeded
    assert completed.stdout == b"cd /var/tmp/apex-run && tar -xf source.tar"


def test_a_run_with_a_transcript_returns_no_output(
    guests: guestshell.GuestShellPort, root: safepaths.RuntimeRoot
) -> None:
    transcript = root.child("runs/build.log")

    completed = guests.run(
        target(root),
        guestshell.GuestRun(
            script=script(),
            deadline=defaults.GUEST_COMMAND_DEADLINE,
            limit=commands.OutputLimit.default(),
            transcript=transcript,
        ),
    )

    assert completed.succeeded
    assert completed.stdout == b""
    if not isinstance(guests, fake_guestshell.ScriptedGuest):
        assert transcript.path.read_bytes() == b"cd /var/tmp/apex-run && tar -xf source.tar"


def test_a_file_sent_to_the_guest_comes_back_intact(
    guests: guestshell.GuestShellPort, root: safepaths.RuntimeRoot, tmp_path: Path
) -> None:
    local = root.path / "source.tar"
    local.write_bytes(b"bundle")
    sent = safepaths.SafePath.regular_file(local, within=root)
    remote = safepaths.RemotePath("/var/tmp/apex-run/source.tar")
    into = root.child("exports/source.tar")

    guests.send(target(root), local=sent, remote=remote, deadline=defaults.TRANSFER_DEADLINE)
    guests.receive(
        target(root), remote=remote, into=into, recursive=False,
        deadline=defaults.TRANSFER_DEADLINE,
    )

    if isinstance(guests, fake_guestshell.ScriptedGuest):
        assert guests.sent == [fake_guestshell.Sent(local=sent, remote=remote)]
        assert guests.received == [
            fake_guestshell.Received(remote=remote, into=into, recursive=False)
        ]
    else:
        assert (tmp_path / "guest/var/tmp/apex-run/source.tar").read_bytes() == b"bundle"
        assert into.path.read_bytes() == b"bundle"


def test_a_guest_user_that_is_not_a_plain_name_is_refused(root: safepaths.RuntimeRoot) -> None:
    with pytest.raises(errors.Refusal) as raised:
        guestshell.GuestTarget(
            user="builder; rm -rf /",
            port=quantities.TcpPort(22244),
            key=root.child("k"),
            known_hosts=root.child("kh"),
        )

    assert raised.value.reason is refusals.RefusalReason.MALFORMED_IDENTIFIER


def test_what_is_written_to_the_run_reaches_the_guest(
    guests: guestshell.GuestShellPort, root: safepaths.RuntimeRoot
) -> None:
    completed = guests.run(
        target(root),
        guestshell.GuestRun(
            script=guestshell.RemoteScript.of(guestshell.Step.of("cat")),
            deadline=defaults.GUEST_COMMAND_DEADLINE,
            limit=commands.OutputLimit.default(),
            stdin=b"request document",
        ),
    )

    assert completed.stdout == b"cat" + b"request document"
