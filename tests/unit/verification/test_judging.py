"""A judged observation carries its verdict in its own proof, and a capture keeps its kind."""

from __future__ import annotations

import json

from apex.kernel import identifiers, verdicts
from apex.verification import faulting, faults, judging


def test_the_verdict_is_written_into_the_observations_and_the_proof_is_those_bytes() -> None:
    found = judging.judge({"changed_pixels": 7, "visible": True}, verdicts.PASSED)

    assert found.verdict is verdicts.PASSED
    assert found.observations == {"changed_pixels": 7, "visible": True, "verdict": "PASS"}
    assert json.loads(found.proof.payload) == found.observations
    assert found.proof.kind == ".json"
    assert found.extras == ()


def test_a_capture_is_offered_under_the_kind_its_name_carries() -> None:
    image = judging.capture(b"png bytes", name="gtk3.png")
    frame = judging.capture(b"P6", name="shell-before.ppm")

    assert (image.kind, image.payload) == (".png", b"png bytes")
    assert frame.kind == ".ppm"


def test_extras_travel_with_the_judgement() -> None:
    image = judging.capture(b"png", name="adwaita.png")

    found = judging.judge({"mode": "adwaita"}, verdicts.BLOCKED, extras=[image])

    assert found.extras == (image,)
    assert found.observations["verdict"] == "BLOCKED"


def test_a_fault_report_is_evidence_of_the_same_shape() -> None:
    case = faults.lookup(identifiers.ProbeId("fault.live-write-denial"))
    report = faulting.report(case, {"status": "PASS"}, reply={"unit": str(case.unit)})
    evidence: judging.Evidence = report

    assert evidence.verdict is verdicts.PASSED
    assert evidence.extras == ()
    assert evidence.proof is report.proof
