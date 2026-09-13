"""The snapshot reads what the host shows and runs what it has, and keeps one report per call."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from apex.adapters.fakes import fake_files, fake_process
from apex.config import defaults
from apex.kernel import safepaths, timing
from apex.ports import portset
from apex.verification import hardwaresnapshot


@pytest.fixture
def root(tmp_path: Path) -> safepaths.RuntimeRoot:
    base = tmp_path / "runtime"
    base.mkdir(mode=0o700)
    return safepaths.RuntimeRoot.adopt(base)


def host(ports: portset.HostPorts, *, tools: dict[str, Path]) -> portset.HostPorts:
    filesystem = fake_files.MemoryFiles()
    shown = {
        "/etc/os-release": b"NAME=Fedora\n",
        "/proc/asound/cards": b" 0 [PCH]: HDA-Intel\n",
        "/proc/asound/card0/codec#0": b"Codec: Realtek ALC294\n",
        "/sys/class/sound/hwC0D0/init_pin_configs": b"0x12 0x90a60130\n",
        "/sys/class/sound/hwC0D0/modelname": b"\n",
        "/sys/bus/usb/devices/1-3/idVendor": b"04f3\n",
        "/sys/bus/usb/devices/1-3/idProduct": b"0c6e\n",
        "/sys/bus/usb/devices/1-3/product": b"ELAN:ARM-M4\n",
        "/sys/bus/usb/devices/1-3/power/runtime_status": b"suspended\n",
        "/sys/bus/usb/devices/1-4/idVendor": b"8087\n",
        "/sys/bus/usb/devices/1-4/idProduct": b"0026\n",
        "/proc/uptime": b"x" * (defaults.SNAPSHOT_READ_LIMIT.value + 1),
    }
    for name, data in shown.items():
        filesystem.write_atomic(safepaths.SafePath(Path(name)), data, mode=defaults.RECORD_MODE)
    processes = fake_process.ScriptedProcess({
        ("uname", "-r"): fake_process.Reply(stdout=b"6.19.0\n"),
        ("amixer", "-c", "0", "contents"): fake_process.Reply(stdout=b"numid=1\n"),
        ("rpm", "-q", *hardwaresnapshot.RPM_PACKAGES): fake_process.Reply(
            exit_code=1, stdout=b"package fprintd is not installed\n"
        ),
    }, known=tools)
    return dataclasses.replace(ports, files=filesystem, processes=processes)


def test_the_report_carries_every_file_every_program_and_the_fingerprint_reader(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    held = host(ports, tools={
        "uname": Path("/usr/bin/uname"),
        "amixer": Path("/usr/bin/amixer"),
        "rpm": Path("/usr/bin/rpm"),
    })

    written = hardwaresnapshot.collect(held, root)

    assert written.path.parent.parent == root.path / defaults.HARDWARE_OBSERVATIONS_DIRECTORY
    assert written.path.name == defaults.OBSERVATIONS_NAME
    assert held.files.mode_of(written) == defaults.RECORD_MODE
    report = json.loads(held.files.read_bytes(written, limit=1 << 24))
    assert report["scope"] == hardwaresnapshot.SCOPE
    assert report["audio_acceptance"] == "NOT TESTED"
    assert report["fingerprint_acceptance"] == "NOT TESTED"
    assert report["cold_boot_provenance"] == "UNKNOWN"
    assert report["created_at"].startswith("20")
    files = report["files"]
    assert files["/etc/os-release"] == {
        "status": "READ", "text": "NAME=Fedora\n", "truncated": False,
    }
    assert files["/proc/cmdline"]["status"] == "UNAVAILABLE"
    assert files["/proc/asound/card0/codec#0"]["status"] == "READ"
    assert files["/sys/class/sound/hwC0D0/init_pin_configs"]["status"] == "READ"
    assert files["/sys/class/sound/hwC0D0/hints"]["status"] == "UNAVAILABLE"
    assert files["/proc/uptime"]["truncated"] is True
    assert len(files["/proc/uptime"]["text"]) == defaults.SNAPSHOT_READ_LIMIT.value
    commands = report["commands"]
    assert commands["kernel"] == {
        "status": "READ", "argv": ["uname", "-r"], "returncode": 0, "stdout": "6.19.0\n",
        "stderr": "", "truncated": False,
    }
    assert commands["pipewire"] == {
        "status": "UNAVAILABLE", "reason": "Tool is not installed", "argv": ["wpctl", "status"],
    }
    assert commands["packages"]["status"] == "UNAVAILABLE"
    assert commands["packages"]["argv"][:2] == ["rpm", "-q"]
    assert commands["card0-mixer"]["stdout"] == "numid=1\n"
    assert report["usb_devices"] == [{
        "path": "/sys/bus/usb/devices/1-3",
        "id": "04f3:0c6e",
        "product": {"status": "READ", "text": "ELAN:ARM-M4\n", "truncated": False},
        "runtime_status": {"status": "READ", "text": "suspended\n", "truncated": False},
    }]


def test_each_call_keeps_its_own_report_and_a_debian_host_asks_dpkg(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    held = host(
        ports, tools={"dpkg-query": Path("/usr/bin/dpkg-query"), "rpm": Path("/usr/bin/rpm")}
    )
    processes = held.processes
    assert isinstance(processes, fake_process.ScriptedProcess)
    processes.expect(
        ("dpkg-query", "-W", *hardwaresnapshot.DEB_PACKAGES),
        fake_process.Reply(stdout=b"fprintd 1.94\n"),
    )

    first = hardwaresnapshot.collect(held, root)
    second = hardwaresnapshot.collect(held, root)

    assert first != second and held.files.exists(first) and held.files.exists(second)
    report = json.loads(held.files.read_bytes(second, limit=1 << 24))
    assert report["commands"]["packages"]["argv"][0] == "dpkg-query"
    assert report["commands"]["kernel"]["status"] == "UNAVAILABLE"


def test_a_program_that_times_out_is_unavailable_with_the_port_s_words(
    ports: portset.HostPorts,
) -> None:
    processes = fake_process.ScriptedProcess(
        {("uname", "-r"): fake_process.Reply(delay=timing.Elapsed(30))},
        known={"uname": Path("/usr/bin/uname")},
    )

    observed = hardwaresnapshot.command(
        dataclasses.replace(ports, processes=processes), ("uname", "-r")
    )

    assert observed["status"] == "UNAVAILABLE" and "exceeded" in str(observed["reason"])
