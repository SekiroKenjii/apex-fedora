"""The screen is captured to a named file and read back; keys go out as the older tool sent them."""

from __future__ import annotations

from pathlib import Path

import pytest

from apex.adapters.fakes import (
    fake_archives,
    fake_clock,
    fake_digesting,
    fake_downloading,
    fake_guestshell,
    fake_hypervisor,
    fake_ids,
    fake_locking,
    fake_process,
    fake_qmp,
    fake_signing,
)
from apex.adapters.real import real_files
from apex.kernel import errors, refusals, safepaths, secrets, timing
from apex.ports import portset
from apex.verification import console

FRAME = b"P6\n1 1\n255\n\x10\x20\x30"


@pytest.fixture
def root(tmp_path: Path) -> safepaths.RuntimeRoot:
    base = tmp_path / "runtime"
    base.mkdir(mode=0o700)
    return safepaths.RuntimeRoot.adopt(base)


def dumped(into: safepaths.SafePath, payload: bytes) -> None:
    """What the hypervisor does on a screendump: the file appears where it was named."""
    into.path.parent.mkdir(parents=True, exist_ok=True)
    into.path.write_bytes(payload)


def bundle(monitor: fake_qmp.ScriptedQmp) -> portset.HostPorts:
    return portset.HostPorts(
        processes=fake_process.ScriptedProcess(),
        files=real_files.LocalFiles(),
        clock=fake_clock.ManualClock(),
        identities=fake_ids.SequenceIdentities(),
        locks=fake_locking.MemoryLocks(),
        digests=fake_digesting.CountingDigests(),
        archives=fake_archives.MemoryArchives(),
        signing=fake_signing.FakeSigner(),
        downloads=fake_downloading.OfflineFetcher({}),
        hypervisor=fake_hypervisor.FakeQemu(),
        monitor=monitor,
        guest=fake_guestshell.ScriptedGuest(),
    )


def test_a_capture_names_the_file_the_hypervisor_writes_and_reads_it_back(
    root: safepaths.RuntimeRoot,
) -> None:
    into = root.child("screens/application.ppm")
    monitor = fake_qmp.ScriptedQmp({"screendump": {}})
    monitor.react("screendump", lambda: dumped(into, FRAME))

    captured = console.capture(bundle(monitor), root.child("qmp.sock"), into=into)

    assert captured == FRAME
    assert monitor.connections == [root.child("qmp.sock")]
    assert [command.name for command in monitor.executed] == ["screendump"]
    assert dict(monitor.executed[0].arguments) == {"filename": str(into)}


def test_a_png_capture_asks_for_that_format(root: safepaths.RuntimeRoot) -> None:
    into = root.child("screens/application.png")
    monitor = fake_qmp.ScriptedQmp({"screendump": {}})
    monitor.react("screendump", lambda: dumped(into, b"png"))

    console.capture(bundle(monitor), root.child("qmp.sock"), into=into)

    assert dict(monitor.executed[0].arguments) == {"filename": str(into), "format": "png"}


def test_a_monitor_that_cannot_be_reached_is_a_port_failure(root: safepaths.RuntimeRoot) -> None:
    monitor = fake_qmp.ScriptedQmp({"screendump": {}}, reachable=False)

    with pytest.raises(errors.PortFailure):
        console.capture(bundle(monitor), root.child("qmp.sock"), into=root.child("x.ppm"))


def test_keys_are_sent_together_as_codes_held_briefly(root: safepaths.RuntimeRoot) -> None:
    monitor = fake_qmp.ScriptedQmp({"send-key": {}})

    console.press(bundle(monitor), root.child("qmp.sock"), "meta_l", "s")

    assert [command.name for command in monitor.executed] == ["send-key"]
    assert dict(monitor.executed[0].arguments) == {
        "keys": [{"type": "qcode", "data": "meta_l"}, {"type": "qcode", "data": "s"}],
        "hold-time": 40,
    }


@pytest.mark.parametrize(
    "text,expected",
    [
        ("a", (("a",),)),
        ("Z", (("shift", "z"),)),
        ("7", (("7",),)),
        ("-_", (("minus",), ("shift", "minus"))),
        (" \n", (("spc",), ("ret",))),
        ("!?~", (("shift", "1"), ("shift", "slash"), ("shift", "grave_accent"))),
        ("[]\\", (("bracket_left",), ("bracket_right",), ("backslash",))),
    ],
)
def test_text_is_mapped_to_the_older_consoles_us_layout_chords(
    text: str, expected: tuple[tuple[str, ...], ...]
) -> None:
    assert console.chords(text) == expected


@pytest.mark.parametrize("text", ["ä", "a\x01", "€"])
def test_a_character_the_layout_cannot_type_is_refused_without_naming_it(text: str) -> None:
    with pytest.raises(errors.Refusal) as caught:
        console.chords(text)

    assert caught.value.reason is refusals.RefusalReason.CONSOLE_TEXT_UNSUPPORTED
    assert text[-1] not in str(caught.value)


def test_a_secret_is_typed_chord_by_chord_with_the_older_pause(root: safepaths.RuntimeRoot) -> None:
    monitor = fake_qmp.ScriptedQmp({"send-key": {}})
    ports = bundle(monitor)

    console.type_secret(ports, root.child("qmp.sock"), secrets.Secret("Ab-1"))

    assert [
        [key["data"] for key in command.arguments["keys"]]  # type: ignore[index,union-attr]
        for command in monitor.executed
    ] == [["shift", "a"], ["b"], ["minus"], ["1"]]
    clock = ports.clock
    assert isinstance(clock, fake_clock.ManualClock)
    assert clock.slept == [timing.Elapsed(0.1)] * 4


def test_an_untypeable_secret_is_refused_before_any_key_is_sent(
    root: safepaths.RuntimeRoot,
) -> None:
    monitor = fake_qmp.ScriptedQmp({"send-key": {}})

    with pytest.raises(errors.Refusal):
        console.typeable(secrets.Secret("pässword"))

    assert monitor.executed == []
