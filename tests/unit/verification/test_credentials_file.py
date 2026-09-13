"""The credentials are read once, checked for shape, and the password never renders."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from apex.adapters.fakes import fake_files
from apex.config import defaults
from apex.kernel import errors, refusals, safepaths, secrets
from apex.verification import testaccess

PATH = safepaths.SafePath(Path("/runtime/test-access/credentials.json"))


def stored(payload: bytes) -> fake_files.MemoryFiles:
    files = fake_files.MemoryFiles()
    files.write_atomic(PATH, payload, mode=defaults.RECORD_MODE)
    return files


def test_the_account_and_its_password_are_read_and_the_password_is_hidden() -> None:
    document = {"user": "apex-test", "password": "s3cret-Word", "key": "k"}
    files = stored(json.dumps(document).encode())

    credentials = testaccess.read(files, PATH)

    assert credentials.user == "apex-test"
    assert credentials.password == secrets.Secret("s3cret-Word")
    assert credentials.key == Path("k")
    assert "s3cret" not in repr(credentials)
    sink = secrets.CollectingSink()
    credentials.password.reveal_into(sink)
    assert sink.collected == "s3cret-Word"


@pytest.mark.parametrize(
    "payload",
    [
        b"not json",
        b"[]",
        json.dumps({"user": "apex-test"}).encode(),
        json.dumps({"user": "", "password": "hunter2"}).encode(),
        json.dumps({"user": "apex-test", "password": 7}).encode(),
    ],
)
def test_a_file_of_another_shape_is_refused_without_its_content(payload: bytes) -> None:
    with pytest.raises(errors.Refusal) as caught:
        testaccess.read(stored(payload), PATH)

    assert caught.value.reason is refusals.RefusalReason.CREDENTIALS_MALFORMED
    assert "hunter2" not in str(caught.value)


def test_a_file_without_a_key_names_none_and_an_empty_key_is_refused() -> None:
    without = testaccess.read(stored(json.dumps({"user": "u", "password": "p"}).encode()), PATH)

    assert without.key is None
    empty = json.dumps({"user": "u", "password": "p", "key": ""}).encode()
    with pytest.raises(errors.Refusal) as caught:
        testaccess.read(stored(empty), PATH)
    assert caught.value.reason is refusals.RefusalReason.CREDENTIALS_MALFORMED
