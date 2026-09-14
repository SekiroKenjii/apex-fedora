"""The installer payload fault recipe on fakes: the request first, the report kept, no mint."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import installerruns
import pytest
from answeringguest import AnsweringGuest

from apex.adapters.fakes import fake_files
from apex.composition import keys as composition_keys
from apex.config import defaults
from apex.kernel import errors, identifiers, refusals, safepaths, verdicts
from apex.model import machines
from apex.ports import guestshell, portset
from apex.verification import installerfault, verifykeys
from apex.verification.recipes import installer_payload_recipe

MACHINE_RUN = identifiers.RunId("e" * 32)
KEY = "-----BEGIN PUBLIC KEY-----\nsynthetic fixture\n"


@pytest.fixture
def root(tmp_path: Path) -> safepaths.RuntimeRoot:
    base = tmp_path / "runtime"
    base.mkdir(mode=0o700)
    (base / "apex-agent.whl").write_bytes(b"not a wheel")
    return safepaths.RuntimeRoot.adopt(base)


def rescue(root: safepaths.RuntimeRoot) -> guestshell.GuestTarget:
    return guestshell.GuestTarget(
        user="root",
        port=defaults.GUEST_SSH_PORT,
        key=root.child(defaults.GUEST_KEY_NAME),
        known_hosts=root.child(defaults.KNOWN_HOSTS_NAME),
    )


def verify(
    ports: portset.HostPorts,
    root: safepaths.RuntimeRoot,
    guest: AnsweringGuest,
    *,
    case: str = installerruns.CASE,
    wrong_key: str | None = None,
    **shape: object,
) -> object:
    held = dataclasses.replace(ports, guest=guest, files=fake_files.MemoryFiles())
    run_directory = root.child(f"vm-runs/{MACHINE_RUN}")
    installerruns.record(held, root, run_directory, **shape)  # type: ignore[arg-type]
    return installer_payload_recipe.verify(
        held,
        guest=rescue(root),
        wheel=safepaths.SafePath.regular_file(root.path / "apex-agent.whl", within=root),
        root=root,
        run_directory=run_directory,
        process=4242,
        case=case,
        wrong_key=wrong_key,
    )


def test_the_plan_writes_the_request_delivers_the_agent_faults_keeps_and_retains() -> None:
    assert [str(item) for item in installer_payload_recipe.PLAN.order] == [
        "installer.request",
        "run.identify",
        "agent.deliver",
        "fault.installer-payload",
        "installer.keep",
        "retain.fault.installer-payload",
    ]
    assert not any(stage.attests for stage in installer_payload_recipe.STAGES)


def test_the_fault_runs_over_the_rescue_shell_and_leaves_the_request_and_the_report(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    guest = AnsweringGuest({"fault.installer-payload": installerruns.confirming()})

    outcome = verify(ports, root, guest)

    assert outcome.succeeded is True  # type: ignore[attr-defined]
    assert outcome.attested == () and outcome.not_tested == ()  # type: ignore[attr-defined]
    assert guest.asked == ["fault.installer-payload"]
    assert guest.requests[0]["arguments"] == {"case": installerruns.CASE, "wrong_public_key": ""}
    facts = outcome.facts  # type: ignore[attr-defined]
    run_directory = root.child(f"vm-runs/{MACHINE_RUN}")
    request = facts[verifykeys.INSTALLER_REQUEST]
    assert request.process == 4242 and request.run == MACHINE_RUN
    assert facts[verifykeys.fault_report(installer_payload_recipe.CASE)].verdict is verdicts.PASSED
    kept = facts[verifykeys.KEPT]
    assert kept.path == run_directory.path / defaults.FAULT_GUEST_NAME
    retained = facts[verifykeys.retained(installer_payload_recipe.CASE)]
    assert retained.path.name == "fault.installer-payload.json"


def test_a_second_attempt_on_the_same_machine_is_refused_before_the_guest_is_touched(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    guest = AnsweringGuest({"fault.installer-payload": installerruns.confirming()})
    held = dataclasses.replace(ports, guest=guest, files=fake_files.MemoryFiles())
    run_directory = root.child(f"vm-runs/{MACHINE_RUN}")
    installerruns.record(held, root, run_directory)
    installerfault.write_request(
        held,
        run_directory,
        installerfault.Request(
            case="missing-signature", image=identifiers.Digest("b" * 64), process=1, run=MACHINE_RUN
        ),
    )

    outcome = installer_payload_recipe.verify(
        held,
        guest=rescue(root),
        wheel=safepaths.SafePath.regular_file(root.path / "apex-agent.whl", within=root),
        root=root,
        run_directory=run_directory,
        process=4242,
        case=installerruns.CASE,
        wrong_key=None,
    )

    assert outcome.refusal is refusals.RefusalReason.FAULT_ALREADY_ATTEMPTED  # type: ignore[attr-defined]
    assert guest.asked == [] and guest.sent == []


def test_a_live_boot_is_not_the_installer_machine_the_fault_needs(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    guest = AnsweringGuest({"fault.installer-payload": installerruns.confirming()})

    outcome = verify(ports, root, guest, medium=machines.Medium.LIVE)

    assert outcome.refusal is refusals.RefusalReason.TOPOLOGY_INCONSISTENT  # type: ignore[attr-defined]
    assert guest.asked == []


def test_the_wrong_key_case_carries_the_key_and_the_pairing_is_refused_otherwise(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    guest = AnsweringGuest({"fault.installer-payload": installerruns.confirming("wrong-key")})

    outcome = verify(ports, root, guest, case="wrong-key", wrong_key=KEY)
    with pytest.raises(errors.Refusal) as refused:
        verify(ports, root, AnsweringGuest({}), case="wrong-key")

    assert outcome.succeeded is True  # type: ignore[attr-defined]
    assert guest.requests[0]["arguments"] == {"case": "wrong-key", "wrong_public_key": KEY}
    assert refused.value.reason is refusals.RefusalReason.REQUEST_MALFORMED


def test_a_report_the_guest_could_not_confirm_is_kept_with_its_own_verdict(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    guest = AnsweringGuest(
        {
            "fault.installer-payload": {
                **installerruns.confirming(),
                "status": "FAIL",
                "returncode": 0,
            }
        }
    )
    held = dataclasses.replace(ports, guest=guest, files=fake_files.MemoryFiles())
    run_directory = root.child(f"vm-runs/{MACHINE_RUN}")
    installerruns.record(held, root, run_directory)

    outcome = installer_payload_recipe.verify(
        held,
        guest=rescue(root),
        wheel=safepaths.SafePath.regular_file(root.path / "apex-agent.whl", within=root),
        root=root,
        run_directory=run_directory,
        process=4242,
        case=installerruns.CASE,
        wrong_key=None,
    )

    assert outcome.succeeded is True  # type: ignore[attr-defined]
    kept = json.loads(
        held.files.read_bytes(
            safepaths.SafePath(run_directory.path / defaults.FAULT_GUEST_NAME), limit=1 << 20
        )
    )
    assert kept["guest"]["verdict"] == "FAIL"
    assert composition_keys.RUN_ID in outcome.facts  # type: ignore[attr-defined]
