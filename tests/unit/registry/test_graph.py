"""Order derived from data dependencies, not written by hand."""

from __future__ import annotations

import pytest

from apex.kernel import errors
from apex.registry import graph


def node(name: str, reads: tuple[str, ...], writes: tuple[str, ...]) -> graph.Node:
    return graph.Node(id=name, reads=frozenset(reads), writes=frozenset(writes))


def test_a_chain_is_ordered_by_what_it_needs() -> None:
    order = graph.order([node("collect", ("output",), ("report",)), node("build", (), ("output",))])

    assert order == ["build", "collect"]


def test_independent_nodes_are_ordered_by_name() -> None:
    order = graph.order([node("zebra", (), ("z",)), node("alpha", (), ("a",))])

    assert order == ["alpha", "zebra"]


def test_the_order_is_the_same_whatever_order_the_nodes_arrive_in() -> None:
    nodes = [node("c", ("b",), ("c",)), node("a", (), ("a",)), node("b", ("a",), ("b",))]

    assert graph.order(nodes) == graph.order(list(reversed(nodes))) == ["a", "b", "c"]


def test_a_cycle_is_reported_with_the_units_involved() -> None:
    with pytest.raises(errors.RegistrationError) as raised:
        graph.order([node("a", ("b",), ("a",)), node("b", ("a",), ("b",))])

    assert "a" in str(raised.value)
    assert "b" in str(raised.value)


def test_a_fact_nobody_writes_is_reported() -> None:
    with pytest.raises(errors.RegistrationError) as raised:
        graph.order([node("a", ("nowhere",), ("a",))])

    assert "nowhere" in str(raised.value)


def test_two_writers_of_one_fact_are_reported() -> None:
    with pytest.raises(errors.RegistrationError) as raised:
        graph.order([node("a", (), ("shared",)), node("b", (), ("shared",))])

    assert "shared" in str(raised.value)


def test_a_seed_fact_satisfies_a_read() -> None:
    order = graph.order([node("a", ("given",), ("a",))], seeds=frozenset({"given"}))

    assert order == ["a"]


def test_an_empty_plan_is_an_empty_order() -> None:
    assert graph.order([]) == []
