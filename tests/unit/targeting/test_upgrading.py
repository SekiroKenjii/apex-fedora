"""An upgrade plan reads the two profiles, the locks and the store, and writes nothing."""

from __future__ import annotations

import dataclasses

from apex.kernel import identifiers
from apex.model import release
from apex.targeting import upgrading
from apex.targeting.releases import fedora44_release

LATER = dataclasses.replace(
    fedora44_release.PROFILE,
    id=identifiers.ProfileId("fedora-45"),
    major=45,
    os_release_version_id="45",
    dist_tag=release.DistTag("fc45"),
    mock_root="fedora-45-x86_64",
)
LOCKS = {
    "fingerprint-rpms.lock.json": '{"rpm": "fprintd-1.94.5-5.fc44.x86_64.rpm"}',
    "sources.lock.json": '{"base": {"reference": "quay.io/x/base@sha256:abc"}}',
    "nvidia.lock.json": '{"mock_root": "fedora-44-x86_64", "tag": "fc44"}',
}


def test_the_changed_fields_are_listed_with_both_values() -> None:
    changes = upgrading.changes(fedora44_release.PROFILE, LATER)

    assert [(c.field, c.current, c.target) for c in changes] == [
        ("id", "fedora-44", "fedora-45"),
        ("major", "44", "45"),
        ("os_release_version_id", "44", "45"),
        ("dist_tag", "fc44", "fc45"),
        ("mock_root", "fedora-44-x86_64", "fedora-45-x86_64"),
    ]


def test_locks_that_name_the_current_release_must_be_reviewed_and_others_are_left() -> None:
    found = upgrading.pins_to_review(fedora44_release.PROFILE, LOCKS)

    assert found == (
        "fingerprint-rpms.lock.json: names fc44",
        "nvidia.lock.json: names fc44, fedora-44-x86_64",
    )


def test_the_plan_carries_the_four_lists_and_declares_no_writes() -> None:
    planned = upgrading.plan(
        fedora44_release.PROFILE,
        LATER,
        locks=LOCKS,
        attestations=["boot.ten-cycles", "audio.speakers"],
    )

    document = planned.document()
    assert document["current"] == "fedora-44" and document["target"] == "fedora-45"
    assert document["capabilities_reobserved"] == []
    assert document["quirks_to_rematch"] == []
    assert document["attestations_to_redo"] == ["audio.speakers", "boot.ten-cycles"]
    assert document["writes"] == []


def test_the_template_is_the_module_to_write_with_the_current_values_to_revise() -> None:
    text = upgrading.template(identifiers.ProfileId("fedora-45"), fedora44_release.PROFILE)

    assert upgrading.module_name(identifiers.ProfileId("fedora-45")) == "fedora45_release.py"
    assert 'id=identifiers.ProfileId("fedora-45")' in text
    assert 'dist_tag=release.DistTag("fc44")' in text
    assert "supported=False" in text
    assert text.startswith('"""fedora-45')
