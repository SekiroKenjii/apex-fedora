"""Unit-bearing scalars that will not add to each other."""

from __future__ import annotations

import pytest

from apex.kernel import errors, quantities


def test_a_size_in_mebibytes_converts_to_bytes() -> None:
    assert quantities.Mib(4096).bytes == 4096 * 1024**2


def test_a_size_in_gibibytes_converts_to_bytes() -> None:
    assert quantities.Gib(24).bytes == 24 * 1024**3


def test_gibibytes_and_mebibytes_do_not_add() -> None:
    with pytest.raises(TypeError):
        quantities.Gib(1) + quantities.Mib(1)  # type: ignore[operator]


def test_the_same_unit_adds() -> None:
    assert quantities.Mib(1024) + quantities.Mib(1024) == quantities.Mib(2048)


def test_a_negative_size_is_refused() -> None:
    with pytest.raises(errors.Refusal):
        quantities.Mib(-1)


def test_a_byte_count_compares_across_units() -> None:
    assert quantities.Gib(1).as_bytes() == quantities.Mib(1024).as_bytes()


@pytest.mark.parametrize("port", [0, -1, 65536, 70000])
def test_an_out_of_range_port_is_refused(port: int) -> None:
    with pytest.raises(errors.Refusal):
        quantities.TcpPort(port)


def test_the_two_ssh_ports_the_project_uses_are_valid_and_distinct() -> None:
    assert quantities.TcpPort(22244) != quantities.TcpPort(22245)


@pytest.mark.parametrize("mode", [0o600, 0o700, 0o644, 0o755])
def test_a_file_mode_accepts_the_permissions_the_project_sets(mode: int) -> None:
    assert quantities.FileMode(mode).value == mode


@pytest.mark.parametrize("mode", [-1, 0o1000, 0o7777 + 1])
def test_a_mode_outside_the_permission_bits_is_refused(mode: int) -> None:
    with pytest.raises(errors.Refusal):
        quantities.FileMode(mode)


def test_a_file_mode_renders_octal() -> None:
    assert str(quantities.FileMode(0o600)) == "0600"
