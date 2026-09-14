"""An anchor carries where it came from, and a bundle can never be its own anchor."""

from __future__ import annotations

import pytest

from apex.kernel import errors, refusals, safepaths
from apex.trust import anchors


def test_an_anchor_from_a_bundle_cannot_be_constructed(root: safepaths.RuntimeRoot) -> None:
    key = root.path / "development-signing.pub"
    key.write_text("public:x")

    with pytest.raises(errors.Refusal) as raised:
        anchors.TrustAnchor(
            public_key=safepaths.RegularFile.adopt(key), provenance=anchors.Provenance.BUNDLE
        )

    assert raised.value.reason is refusals.RefusalReason.TRUST_ANCHOR_FROM_BUNDLE


def test_an_operator_supplied_key_becomes_an_anchor(root: safepaths.RuntimeRoot) -> None:
    key = root.path / "trusted.pub"
    key.write_text("public:x")

    anchor = anchors.operator_supplied(key)

    assert anchor.provenance is anchors.Provenance.OPERATOR_SUPPLIED
    assert anchor.public_key.path == key.resolve()


def test_a_key_inside_the_judged_directory_is_not_independent(root: safepaths.RuntimeRoot) -> None:
    (root.path / "output").mkdir()
    key = root.path / "output" / "development-signing.pub"
    key.write_text("public:x")
    anchor = anchors.operator_supplied(key)

    with pytest.raises(errors.Refusal) as raised:
        anchors.require_independent(anchor, of=root.child("output"))

    assert raised.value.reason is refusals.RefusalReason.TRUST_ANCHOR_FROM_BUNDLE


def test_a_key_beside_the_judged_directory_is_independent(root: safepaths.RuntimeRoot) -> None:
    (root.path / "output").mkdir()
    key = root.path / "trusted.pub"
    key.write_text("public:x")

    anchors.require_independent(anchors.operator_supplied(key), of=root.child("output"))
