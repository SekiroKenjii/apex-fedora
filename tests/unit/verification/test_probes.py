"""A probe case names a guest unit that exists, and its answer becomes proof unchanged."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from apex.adapters.fakes import fake_guestshell
from apex.agent import units
from apex.composition import agentrun
from apex.config import defaults
from apex.kernel import claims, errors, identifiers, safepaths
from apex.model import serialframe
from apex.ports import guestshell, portset
from apex.verification import probes, probing

TOKEN = identifiers.Token("f" * 32)
SOURCE = Path(__file__).resolve().parents[3] / "src" / "apex" / "verification" / "probes"


def test_every_probe_module_declares_one_case_and_the_registry_holds_them_all() -> None:
    modules = sorted(p for p in SOURCE.glob("*.py") if not p.name.startswith("_"))

    assert len(probes.registered()) == len(modules)
    assert [str(case.unit) for case in probes.registered()] == [
        "desktop.greeter",
        "desktop.overview",
        "desktop.render",
        "desktop.session",
        "desktop.shell-startup",
        "desktop.theme-adwaita",
        "desktop.theme-gtk3",
        "desktop.theme-settings",
        "fixture.installer-disks",
        "guest.diagnostics",
        "installer.diagnostics",
        "live.observe",
        "recovery.installed",
        "recovery.prerequisites",
        "ventoy.observe",
    ]


def test_every_case_names_a_unit_the_agent_declares() -> None:
    declared = {str(unit.id) for unit in units.registered()}

    assert {str(case.unit) for case in probes.registered()} <= declared


def test_an_unknown_probe_is_refused_by_name() -> None:
    with pytest.raises(errors.Refusal, match="agent.unit-unknown"):
        probes.lookup(identifiers.ProbeId("live.invented"))


def test_the_builder_is_a_guest_a_probe_can_stand_in() -> None:
    case = probing.ProbeCase(
        unit=identifiers.ProbeId("live.observe"),
        environment=claims.EnvironmentKind.BUILD,
        summary="x",
    )

    assert case.environment is claims.EnvironmentKind.BUILD


@pytest.mark.parametrize(
    "environment", [claims.EnvironmentKind.SIMULATED, claims.EnvironmentKind.OPERATOR]
)
def test_a_case_that_observes_no_guest_is_a_registration_fault(
    environment: claims.EnvironmentKind,
) -> None:
    with pytest.raises(errors.RegistrationError):
        probing.ProbeCase(
            unit=identifiers.ProbeId("live.observe"), environment=environment, summary="x"
        )


def test_a_case_without_a_summary_is_a_registration_fault() -> None:
    with pytest.raises(errors.RegistrationError):
        probing.ProbeCase(
            unit=identifiers.ProbeId("live.observe"),
            environment=claims.EnvironmentKind.LIVE_VM,
            summary="",
        )


@pytest.fixture
def root(tmp_path: Path) -> safepaths.RuntimeRoot:
    base = tmp_path / "runtime"
    base.mkdir(mode=0o700)
    (base / "builder_ed25519").write_bytes(b"")
    return safepaths.RuntimeRoot.adopt(base)


def target(root: safepaths.RuntimeRoot) -> guestshell.GuestTarget:
    return guestshell.GuestTarget(
        user=defaults.BUILDER_USER,
        port=defaults.GUEST_SSH_PORT,
        key=safepaths.SafePath.regular_file(root.path / "builder_ed25519", within=root),
        known_hosts=root.child(defaults.KNOWN_HOSTS_NAME),
    )


def test_the_answer_is_held_as_json_proof_exactly_as_the_guest_sent_it(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    guest = ports.guest
    assert isinstance(guest, fake_guestshell.ScriptedGuest)
    document = {"protocol": 1, "unit": "live.observe", "observations": {"scope": "x", "n": 1}}
    lines = serialframe.encode(json.dumps(document).encode(), token=TOKEN)
    script = (
        "cd /var/tmp/apex-run/agent && sudo flock -n /run/apex-build.lock bash -c "
        "'env PYTHONPATH=/var/tmp/apex-run/agent/lib python3 -m apex.agent.main run "
        f"--framed {TOKEN}'"
    )
    guest.expect(script, fake_guestshell.GuestReply(stdout=b"\n".join(lines) + b"\n"))
    install = agentrun.AgentInstall(
        directory=safepaths.RemotePath("/var/tmp/apex-run/agent"),
        digest=identifiers.Digest("a" * 64),
    )
    case = probes.lookup(identifiers.ProbeId("live.observe"))

    observed = probing.observe(ports, target(root), install, case, token=TOKEN)

    assert observed.case is case
    assert observed.observations == {"scope": "x", "n": 1}
    assert observed.proof.kind == ".json"
    assert json.loads(observed.proof.payload) == document
    sent = guest.runs[-1]
    assert sent.stdin is not None
    assert json.loads(sent.stdin)["unit"] == "live.observe"


def test_the_desktop_cases_are_asked_as_the_session_s_user_without_the_lock(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    guest = ports.guest
    assert isinstance(guest, fake_guestshell.ScriptedGuest)
    document = {
        "protocol": 1, "unit": "desktop.render", "observations": {"presented": True},
    }
    lines = serialframe.encode(json.dumps(document).encode(), token=TOKEN)
    script = (
        "cd /var/tmp/apex-run/agent && "
        "env PYTHONPATH=/var/tmp/apex-run/agent/lib python3 -m apex.agent.main run "
        f"--framed {TOKEN}"
    )
    guest.expect(script, fake_guestshell.GuestReply(stdout=b"\n".join(lines) + b"\n"))
    install = agentrun.AgentInstall(
        directory=safepaths.RemotePath("/var/tmp/apex-run/agent"),
        digest=identifiers.Digest("a" * 64),
    )
    case = probes.lookup(identifiers.ProbeId("desktop.render"))

    observed = probing.observe(ports, target(root), install, case, token=TOKEN)

    assert not case.privileged
    assert observed.observations == {"presented": True}
    assert "sudo" not in guest.runs[-1].script.rendered()
    for name in ("desktop.theme-gtk3", "desktop.theme-adwaita", "desktop.theme-settings"):
        assert not probes.lookup(identifiers.ProbeId(name)).privileged
    assert probes.lookup(identifiers.ProbeId("live.observe")).privileged
