"""A secret cannot be rendered, so it cannot leak into a report by accident."""

from __future__ import annotations

import json

import pytest

from apex.kernel import errors, secrets


def test_the_representation_is_redacted() -> None:
    assert repr(secrets.Secret("hunter2")) == "<redacted>"


def test_rendering_as_text_is_refused() -> None:
    with pytest.raises(errors.Refusal):
        str(secrets.Secret("hunter2"))


def test_formatting_is_refused() -> None:
    with pytest.raises(errors.Refusal):
        f"{secrets.Secret('hunter2')}"


def test_serialising_is_refused() -> None:
    with pytest.raises(TypeError):
        json.dumps({"password": secrets.Secret("hunter2")})


def test_the_value_reaches_a_declared_sink_and_nowhere_else() -> None:
    sink = secrets.CollectingSink()

    secrets.Secret("hunter2").reveal_into(sink)

    assert sink.collected == "hunter2"


def test_two_secrets_with_the_same_value_compare_equal() -> None:
    assert secrets.Secret("a") == secrets.Secret("a")


def test_a_credential_handle_names_its_purpose_and_lifetime() -> None:
    handle = secrets.CredentialHandle(
        purpose="qcow2-test-access", lifetime=secrets.Lifetime.DISPOSABLE_FIXTURE
    )

    assert handle.purpose == "qcow2-test-access"
    assert handle.lifetime is secrets.Lifetime.DISPOSABLE_FIXTURE


def test_a_handle_holds_no_material() -> None:
    handle = secrets.CredentialHandle(purpose="p", lifetime=secrets.Lifetime.BUILDER_RESIDENT)

    assert "hunter2" not in repr(handle)
