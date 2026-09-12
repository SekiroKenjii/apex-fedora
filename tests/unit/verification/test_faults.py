"""A fault case names a guest unit that exists, and a report's status becomes a verdict."""

from __future__ import annotations

from pathlib import Path

import pytest

from apex.agent import units
from apex.attestation import catalogue
from apex.kernel import claims, errors, identifiers, verdicts
from apex.verification import faulting, faults

SOURCE = Path(__file__).resolve().parents[3] / "src" / "apex" / "verification" / "faults"


def test_every_fault_module_declares_one_case_and_the_registry_holds_them_all() -> None:
    modules = sorted(p for p in SOURCE.glob("*.py") if not p.name.startswith("_"))

    assert len(faults.registered()) == len(modules)
    assert [str(case.unit) for case in faults.registered()] == [
        "fault.fingerprint-cleanup",
        "fault.installer-payload",
        "fault.installer-trust",
        "fault.live-lock",
        "fault.live-write-denial",
        "fault.usb-write-denial",
    ]


def test_every_case_names_a_unit_the_agent_declares() -> None:
    declared = {str(unit.id) for unit in units.registered()}

    assert {str(case.unit) for case in faults.registered()} <= declared


def test_an_unknown_fault_is_refused_by_name() -> None:
    with pytest.raises(errors.Refusal, match="agent.unit-unknown"):
        faults.lookup(identifiers.ProbeId("fault.invented"))


def test_the_builder_s_own_cases_stand_in_the_build_environment_the_catalogue_names() -> None:
    for name in ("fault.fingerprint-cleanup", "fault.installer-trust"):
        case = faults.lookup(identifiers.ProbeId(name))

        assert case.environment is claims.EnvironmentKind.BUILD
    for check in ("fingerprint.virtual-cleanup", "signature.accept", "signature.reject"):
        required = catalogue.specification(identifiers.CheckId(check)).environment

        assert required is claims.EnvironmentKind.BUILD


@pytest.mark.parametrize(
    "environment", [claims.EnvironmentKind.SIMULATED, claims.EnvironmentKind.OPERATOR]
)
def test_a_case_attempted_outside_a_guest_is_a_registration_fault(
    environment: claims.EnvironmentKind,
) -> None:
    with pytest.raises(errors.RegistrationError):
        faulting.FaultCase(
            unit=identifiers.ProbeId("fault.live-write-denial"),
            environment=environment,
            summary="x",
        )


@pytest.mark.parametrize(
    "status,expected",
    [("PASS", verdicts.PASSED), ("FAIL", verdicts.FAILED), ("BLOCKED", verdicts.BLOCKED)],
)
def test_a_reported_status_is_the_verdict_it_names(status: str, expected: verdicts.Verdict) -> None:
    assert faulting.judge({"status": status}) == expected


@pytest.mark.parametrize("observations", [{}, {"status": "OK"}, {"status": 1}])
def test_a_report_without_a_known_status_is_blocked_never_passed(
    observations: dict[str, object],
) -> None:
    assert faulting.judge(observations) == verdicts.BLOCKED  # type: ignore[arg-type]


def test_the_proof_is_the_whole_reply_and_the_verdict_is_the_report_s() -> None:
    case = faults.lookup(identifiers.ProbeId("fault.live-write-denial"))
    reply = {"protocol": 1, "unit": str(case.unit), "observations": {"status": "FAIL", "n": 1}}

    found = faulting.report(case, {"status": "FAIL", "n": 1}, reply=reply)

    assert found.verdict == verdicts.FAILED
    assert found.proof.kind == ".json"
    assert b'"unit":"fault.live-write-denial"' in found.proof.payload
