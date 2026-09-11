"""The refusing double answers every method every port declares, and refuses each one.

It is generated from the name that is asked for, so a port that grows a method cannot leave
a gap that a stage slips through during planning.
"""

from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path

import pytest

from apex.kernel import claims, errors
from apex.ports import planning, portset

PORTS = Path(portset.__file__).parent
NOT_PORTS = {"portset", "planning"}


def protocols() -> list[tuple[str, type]]:
    found = []
    for item in pkgutil.iter_modules([str(PORTS)]):
        if item.name in NOT_PORTS:
            continue
        module = importlib.import_module(f"apex.ports.{item.name}")
        for name, value in vars(module).items():
            if isinstance(value, type) and name.endswith("Port"):
                found.append((f"{item.name}.{name}", value))
    return sorted(found)


def declared_methods(protocol: type) -> list[str]:
    return sorted(
        name
        for name, value in vars(protocol).items()
        if callable(value) and not name.startswith("_")
    )


@pytest.mark.parametrize("label,protocol", protocols())
def test_every_declared_method_is_refused(label: str, protocol: type) -> None:
    double = planning.Refusing(label)
    methods = declared_methods(protocol)

    assert methods, f"{label} declares no method"
    for method in methods:
        with pytest.raises(errors.InternalDefect) as raised:
            getattr(double, method)()
        assert method in str(raised.value)


def test_the_double_attests_only_simulation() -> None:
    assert planning.Refusing("clock").environment is claims.EnvironmentKind.SIMULATED


def test_the_double_does_not_invent_private_attributes() -> None:
    with pytest.raises(AttributeError):
        planning.Refusing("clock")._anything  # noqa: B018


def test_a_planning_bundle_cannot_authorise_anything(ports_of_fakes: portset.HostPorts) -> None:
    planned = ports_of_fakes.for_planning()

    assert planned.environment is claims.EnvironmentKind.SIMULATED
    with pytest.raises(errors.Refusal):
        planned.require_attestable()
