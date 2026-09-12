"""The pinned file set is parsed into types before a single network request."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from apex.kernel import errors, refusals
from apex.model import pinnedfiles

REPOSITORY = Path(__file__).resolve().parents[3]
LOCK = REPOSITORY / "config" / "fingerprint-tests.lock.json"


def reviewed() -> dict[str, Any]:
    document: dict[str, Any] = json.loads(LOCK.read_text())
    return document


def test_the_reviewed_lock_in_this_repository_parses() -> None:
    parsed = pinnedfiles.parse(reviewed())

    assert parsed.version == "1.94.5"
    assert parsed.names == {"fprintd.py", "output_checker.py", "dbusmock/polkitd.py"}
    assert str(parsed.base).startswith("https://")
    nested = next(item for item in parsed.files if item.name == "dbusmock/polkitd.py")
    assert str(nested.url(parsed.base)) == f"{parsed.base}dbusmock/polkitd.py"
    assert nested.sha256.hex == reviewed()["files"]["dbusmock/polkitd.py"]


EDITS: dict[str, tuple[tuple[str, ...], object]] = {
    "no-version": (("version",), None),
    "http-base": (("base_url",), "http://example.invalid/tests/"),
    "no-base": (("base_url",), None),
    "empty-files": (("files",), {}),
    "short-checksum": (("files", "fprintd.py"), "abc"),
    "climbing-name": (("files", "../fprintd.py"), "0" * 64),
    "absolute-name": (("files", "/etc/fprintd.py"), "0" * 64),
    "empty-name": (("files", ""), "0" * 64),
}


def damaged(name: str) -> object:
    document = copy.deepcopy(reviewed())
    if name == "not-an-object":
        return [document]
    path, value = EDITS[name]
    holder: dict[str, Any] = document
    for key in path[:-1]:
        holder = holder[key]
    if value is None:
        del holder[path[-1]]
    else:
        holder[path[-1]] = value
    return document


@pytest.mark.parametrize(
    "name,reason",
    [
        ("not-an-object", refusals.RefusalReason.LOCK_SCHEMA_UNSUPPORTED),
        ("no-version", refusals.RefusalReason.LOCK_ENTRY_MALFORMED),
        ("http-base", refusals.RefusalReason.URL_NOT_HTTPS),
        ("no-base", refusals.RefusalReason.URL_NOT_HTTPS),
        ("empty-files", refusals.RefusalReason.LOCK_SOURCES_EMPTY),
        ("short-checksum", refusals.RefusalReason.LOCK_CHECKSUM_MALFORMED),
        ("climbing-name", refusals.RefusalReason.FILENAME_NOT_PLAIN),
        ("absolute-name", refusals.RefusalReason.FILENAME_NOT_PLAIN),
        ("empty-name", refusals.RefusalReason.LOCK_ENTRY_MALFORMED),
    ],
)
def test_each_way_the_lock_can_be_wrong_is_refused_for_its_reason(
    name: str, reason: refusals.RefusalReason
) -> None:
    with pytest.raises(errors.Refusal) as raised:
        pinnedfiles.parse(damaged(name))

    assert raised.value.reason is reason
