"""A hook the rules do not answer is refused under its own reason."""

from __future__ import annotations

import pytest

from apex.cli import hookdispatch
from apex.kernel import errors, refusals


def test_an_unknown_hook_kind_is_a_hook_fault_not_a_settings_fault() -> None:
    with pytest.raises(errors.PreconditionUnmet) as raised:
        hookdispatch.run(["post-checkout"], "", "")

    assert raised.value.reason is refusals.RefusalReason.HOOK_KIND_UNKNOWN


def test_a_missing_hook_kind_is_reported_the_same_way() -> None:
    with pytest.raises(errors.PreconditionUnmet) as raised:
        hookdispatch.run([], "", "")

    assert raised.value.reason is refusals.RefusalReason.HOOK_KIND_UNKNOWN
