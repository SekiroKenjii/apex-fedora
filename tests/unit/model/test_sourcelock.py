"""The reviewed source lock, parsed into types before a single network request."""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from apex.kernel import errors, refusals
from apex.model import sourcelock

REPOSITORY = Path(__file__).resolve().parents[3]
FAULTS = {
    "schema": refusals.RefusalReason.LOCK_SCHEMA_UNSUPPORTED,
    "missing-image": refusals.RefusalReason.LOCK_IMAGE_MISSING,
    "mutable-image": refusals.RefusalReason.LOCK_IMAGE_REFERENCE_MUTABLE,
    "mismatched-image": refusals.RefusalReason.LOCK_IMAGE_REFERENCE_MUTABLE,
    "missing-digest": refusals.RefusalReason.LOCK_IMAGE_DIGEST_MALFORMED,
    "empty-sources": refusals.RefusalReason.LOCK_SOURCES_EMPTY,
    "missing-checksum": refusals.RefusalReason.LOCK_CHECKSUM_MALFORMED,
    "short-checksum": refusals.RefusalReason.LOCK_CHECKSUM_MALFORMED,
    "http": refusals.RefusalReason.URL_NOT_HTTPS,
    "branch": refusals.RefusalReason.LOCK_COMMIT_NOT_OBJECT_ID,
    "path": refusals.RefusalReason.FILENAME_NOT_PLAIN,
    "duplicate": refusals.RefusalReason.LOCK_FILENAME_DUPLICATE,
    "bad-entry": refusals.RefusalReason.LOCK_ENTRY_MALFORMED,
}


def reviewed() -> dict[str, object]:
    document: dict[str, object] = json.loads(
        (REPOSITORY / "config" / "sources.lock.json").read_text()
    )
    return document


def _collide(sources: dict[str, dict[str, object]]) -> None:
    sources["shadcn-gnome"]["filename"] = "collision.tar.gz"
    sources["macos-genie"]["filename"] = "collision.tar.gz"


def _demote_url(sources: dict[str, dict[str, object]]) -> None:
    url = sources["shadcn-gnome"]["url"]
    assert isinstance(url, str)
    sources["shadcn-gnome"]["url"] = url.replace("https:", "http:")


MUTATIONS: dict[str, Callable[[dict[str, Any]], None]] = {
    "schema": lambda lock: lock.update(schema=True),
    "missing-image": lambda lock: lock.pop("base"),
    "mutable-image": lambda lock: lock["image_builder"].update(
        reference="ghcr.io/osbuild/image-builder-cli:latest"
    ),
    "mismatched-image": lambda lock: lock["image_builder"].update(digest="sha256:" + "0" * 64),
    "missing-digest": lambda lock: lock["base"].pop("digest"),
    "empty-sources": lambda lock: lock.update(sources={}),
    "missing-checksum": lambda lock: lock["sources"]["shadcn-gnome"].pop("sha256"),
    "short-checksum": lambda lock: lock["sources"]["shadcn-gnome"].update(sha256="abcd"),
    "http": lambda lock: _demote_url(lock["sources"]),
    "branch": lambda lock: lock["sources"]["shadcn-gnome"].update(commit="main"),
    "path": lambda lock: lock["sources"]["shadcn-gnome"].update(filename="../outside.tar.gz"),
    "duplicate": lambda lock: _collide(lock["sources"]),
    "bad-entry": lambda lock: lock["sources"].update({"shadcn-gnome": []}),
}


def faulted(name: str) -> dict[str, object]:
    lock = copy.deepcopy(reviewed())
    MUTATIONS[name](lock)
    return lock


def test_the_reviewed_lock_parses() -> None:
    lock = sourcelock.parse(reviewed())

    assert [image.name for image in lock.images] == ["base", "image_builder"]
    assert len(lock.sources) == 6
    by_name = {source.name: source for source in lock.sources}
    assert str(by_name["maple-mono-nf"].filename) == "MapleMono-NF.zip"
    assert str(by_name["shadcn-gnome"].filename) == "shadcn-gnome.tar.gz"
    assert by_name["shadcn-gnome"].commit is not None


@pytest.mark.parametrize("fault", sorted(FAULTS))
def test_every_fault_is_refused_with_its_own_reason(fault: str) -> None:
    with pytest.raises(errors.Refusal) as raised:
        sourcelock.parse(faulted(fault))

    assert raised.value.reason is FAULTS[fault]


def test_a_lock_that_is_not_a_document_is_refused() -> None:
    with pytest.raises(errors.Refusal) as raised:
        sourcelock.parse([])

    assert raised.value.reason is refusals.RefusalReason.LOCK_SCHEMA_UNSUPPORTED
