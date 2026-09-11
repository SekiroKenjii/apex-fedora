"""Every negative is one file, declares the reason it expects, and is registered by being there."""

from __future__ import annotations

from pathlib import Path

from apex.kernel import refusals
from apex.trust import negatives

SOURCE = Path(negatives.__file__).parent


def test_every_module_in_the_package_is_one_registered_negative() -> None:
    modules = sorted(p.stem for p in SOURCE.glob("*_negative.py"))

    assert len(negatives.registered()) == len(modules) == 4


def test_the_registered_negatives_cover_the_four_ways_a_bundle_can_lie() -> None:
    expected = {
        "trust.changed-manifest": refusals.RefusalReason.SIGNATURE_REJECTED,
        "trust.changed-payload": refusals.RefusalReason.ARTIFACT_CHECKSUM_MISMATCH,
        "trust.untrusted-key": refusals.RefusalReason.SIGNATURE_REJECTED,
        "trust.bundled-key": refusals.RefusalReason.TRUST_ANCHOR_FROM_BUNDLE,
    }

    assert {str(item.id): item.expects for item in negatives.registered()} == expected
