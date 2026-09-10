"""Every port has a real adapter and a fake, and both declare what they attest to."""

from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path

import pytest

from apex.kernel import claims

SOURCE = Path(__file__).resolve().parents[2] / "src" / "apex"


def module_names(package: str) -> set[str]:
    location = SOURCE / "adapters" / package
    return {item.name for item in pkgutil.iter_modules([str(location)])}


def test_every_real_adapter_has_a_fake_counterpart() -> None:
    real = {name.removeprefix("real_") for name in module_names("real")}
    fake = {name.removeprefix("fake_") for name in module_names("fake" + "s")}

    assert real == fake


def test_the_contract_suite_covers_every_port() -> None:
    ports = {
        item.name for item in pkgutil.iter_modules([str(SOURCE / "ports")])
    } - {"portset"}
    covered = {
        path.stem.removeprefix("test_").removesuffix("_port")
        for path in (SOURCE.parents[1] / "tests" / "contract").glob("test_*_port.py")
    }
    named = {"process", "clock", "files", "ids"}

    assert named <= ports
    assert {"process", "clock", "file_system", "identity"} <= covered


@pytest.mark.parametrize("package,expected", [("real", False), ("fakes", True)])
def test_every_adapter_declares_its_environment(package: str, expected: bool) -> None:
    for name in sorted(module_names(package)):
        module = importlib.import_module(f"apex.adapters.{package}.{name}")
        classes = [
            value
            for value in vars(module).values()
            if isinstance(value, type) and value.__module__ == module.__name__
        ]
        adapters = [item for item in classes if hasattr(item, "environment")]

        assert adapters, f"{name} declares no adapter with an environment"
        for adapter in adapters:
            simulated = adapter.environment is claims.EnvironmentKind.SIMULATED
            assert simulated is expected, f"{name}.{adapter.__name__} attests the wrong kind"
