"""The guest state probe runs the same observations the older script ran, through a port."""

from __future__ import annotations

from apex.adapters.fakes import (
    fake_archives,
    fake_clock,
    fake_containers,
    fake_digesting,
    fake_extents,
    fake_files,
    fake_ids,
    fake_process,
)
from apex.agent import agentports, units
from apex.agent.units import state_probe_unit
from apex.kernel import identifiers

OLDER_OBSERVATIONS = {
    "bootc": ("bootc", "status", "--format", "json"),
    "gdm": ("systemctl", "is-active", "gdm"),
    "dbus": (
        "busctl", "--system", "call", "org.freedesktop.DBus", "/org/freedesktop/DBus",
        "org.freedesktop.DBus", "GetId",
    ),
    "root_mount": ("findmnt", "--noheadings", "--output", "TARGET,SOURCE,FSTYPE,OPTIONS", "/"),
    "failed_units": ("systemctl", "--failed", "--no-legend"),
    "sessions": ("loginctl", "list-sessions", "--no-legend"),
    "selinux": ("getenforce",),
    "kernel": ("uname", "-r"),
}


def scripted() -> fake_process.ScriptedProcess:
    process = fake_process.ScriptedProcess()
    for name, argv in OLDER_OBSERVATIONS.items():
        process.expect(argv, fake_process.Reply(stdout=f"{name} output\n".encode()))
    process.expect(("getenforce",), fake_process.Reply(stdout=b"Enforcing\n"))
    process.expect(
        ("systemctl", "is-active", "gdm"), fake_process.Reply(exit_code=3, stdout=b"inactive\n")
    )
    return process


def bundle(process: fake_process.ScriptedProcess) -> agentports.AgentPorts:
    return agentports.AgentPorts(
        processes=process, files=fake_files.MemoryFiles(), clock=fake_clock.ManualClock(),
        containers=fake_containers.FakeRegistry(),
        digests=fake_digesting.CountingDigests(),
        archives=fake_archives.MemoryArchives(),
        identities=fake_ids.SequenceIdentities(),
        extents=fake_extents.FakeExtents(),
    )


def test_the_probe_runs_exactly_the_older_observation_set() -> None:
    process = scripted()

    state_probe_unit.run(bundle(process), arguments={})

    assert sorted(tuple(call) for call in process.calls) == sorted(OLDER_OBSERVATIONS.values())


def test_the_report_has_the_older_shape_and_never_claims_a_visual_test() -> None:
    report = state_probe_unit.run(bundle(scripted()), arguments={})

    assert report["visual_test"] == "NOT TESTED"
    observations = report["observations"]
    assert isinstance(observations, dict)
    assert set(observations) == set(OLDER_OBSERVATIONS)
    assert observations["selinux"] == {"returncode": 0, "stdout": "Enforcing", "stderr": ""}
    assert observations["gdm"] == {"returncode": 3, "stdout": "inactive", "stderr": ""}


def test_a_missing_program_is_recorded_not_raised() -> None:
    process = scripted()
    process.expect(("getenforce",), fake_process.Reply(missing=True))

    report = state_probe_unit.run(bundle(process), arguments={})

    observations = report["observations"]
    assert isinstance(observations, dict)
    selinux = observations["selinux"]
    assert isinstance(selinux, dict)
    assert selinux["returncode"] is None
    assert "error" in selinux


def test_the_unit_is_registered_under_its_identifier() -> None:
    registered = units.registered()

    assert identifiers.ProbeId("guest.state") in {unit.id for unit in registered}
    assert len(registered) == len(list(units.DIRECTORY.glob("*_unit.py")))
