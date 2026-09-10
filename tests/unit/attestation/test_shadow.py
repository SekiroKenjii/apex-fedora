"""The new fold must agree with the one it replaces, on a store with every awkward shape."""

from __future__ import annotations

from pathlib import Path

from apex.attestation import readiness, resolving
from migration import readiness_shadow, synthetic_root


def test_the_two_folds_agree_except_where_the_new_one_is_deliberately_stricter(
    tmp_path: Path,
) -> None:
    root = synthetic_root.build(tmp_path / "runtime")
    result = readiness_shadow.compare(root)

    assert result["disagreements"] == []
    assert result["legacy_ready"] == result["new_ready"]


def test_the_one_accepted_divergence_is_the_altered_proof(tmp_path: Path) -> None:
    """Legacy drops the record and reports not tested. Blocking it is the improvement."""
    root = synthetic_root.build(tmp_path / "runtime")

    accepted = readiness_shadow.compare(root)["accepted_divergences"]

    assert [item["check"] for item in accepted] == ["live.direct"]
    assert accepted[0]["legacy"] == "NOT TESTED"
    assert accepted[0]["new"] == "BLOCKED"


def test_the_deliberately_corrupted_proof_is_blocked_not_passed(tmp_path: Path) -> None:
    root = synthetic_root.build(tmp_path / "runtime")
    records, candidate = resolving.resolve_store(root)

    fresh = readiness.evaluate(
        required=resolving.required_environments(), records=records, candidate=candidate
    )

    assert fresh.verdicts["live.direct"].stored_name == "BLOCKED"
    assert any("live.direct" in fault for fault in fresh.faults)


def test_resolving_re_reads_the_proof_bytes_every_time(tmp_path: Path) -> None:
    """A digest trusted from metadata is a digest an editor can change."""
    root = synthetic_root.build(tmp_path / "runtime")
    records, _ = resolving.resolve_store(root)
    before = {str(item.check): item.proofs_intact for item in records}

    target = root / "evidence" / "0dff0c4156f3476cafc5decf611fa714" / "0-summary.json"
    target.write_text('{"boots": 0}\n')
    after = {
        str(item.check): item.proofs_intact for item in resolving.resolve_store(root)[0]
    }

    assert before["boot.ten-cycles"]
    assert not after["boot.ten-cycles"]
