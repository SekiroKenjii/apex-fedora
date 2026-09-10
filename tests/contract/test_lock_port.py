"""Taking a lock. A refusal names the holder rather than hanging in silence."""

from __future__ import annotations

import pytest

from apex.kernel import errors, refusals, timing
from apex.ports import locking as locking_port


def scope() -> locking_port.LockScope:
    return locking_port.LockScope("build")


def immediate() -> locking_port.AcquisitionPolicy:
    return locking_port.AcquisitionPolicy.immediate()


def bounded_wait() -> locking_port.AcquisitionPolicy:
    return locking_port.AcquisitionPolicy.wait(timing.Elapsed(0.05))


def test_an_uncontended_lock_is_granted(locks: locking_port.LockPort) -> None:
    with locks.acquire(scope(), immediate()) as lease:
        assert lease.scope == scope()


def test_a_lease_records_who_holds_it(locks: locking_port.LockPort) -> None:
    with locks.acquire(scope(), immediate()) as lease:
        assert lease.holder


def test_the_holder_is_readable_while_the_lock_is_held(
    locks: locking_port.LockPort,
) -> None:
    with locks.acquire(scope(), immediate()) as lease:
        assert locks.holder(scope()) == lease.holder


def test_a_released_lock_reports_no_holder(locks: locking_port.LockPort) -> None:
    with locks.acquire(scope(), immediate()):
        pass

    assert locks.holder(scope()) is None


def test_a_contended_lock_refuses_immediately_and_names_the_holder(
    locks: locking_port.LockPort,
) -> None:
    with locks.acquire(scope(), immediate()) as held:
        holder = held.holder
        with pytest.raises(errors.Refusal) as raised:
            locks.acquire(scope(), immediate()).__enter__()

    assert raised.value.reason is refusals.RefusalReason.LOCK_HELD
    assert holder in str(raised.value)


def test_a_bounded_wait_gives_up_rather_than_hanging(
    locks: locking_port.LockPort,
) -> None:
    with locks.acquire(scope(), immediate()), pytest.raises(errors.Refusal):
        locks.acquire(scope(), bounded_wait()).__enter__()


def test_two_different_scopes_do_not_contend(locks: locking_port.LockPort) -> None:
    with (
        locks.acquire(locking_port.LockScope("build"), immediate()),
        locks.acquire(locking_port.LockScope("machine"), immediate()) as second,
    ):
        assert second.scope == locking_port.LockScope("machine")


def test_a_lock_is_reusable_after_release(locks: locking_port.LockPort) -> None:
    with locks.acquire(scope(), immediate()):
        pass

    with locks.acquire(scope(), immediate()) as second:
        assert second.holder


def test_a_refused_acquirer_does_not_erase_the_holder(locks: locking_port.LockPort) -> None:
    """Releasing on the path where nothing was taken clears a record someone else wrote.

    The lock is advisory, so a process that merely opened the file can truncate it. The first
    refusal then names the holder and every refusal after it says nothing, which is the one
    thing this port exists to avoid.
    """
    scope = locking_port.LockScope("build")

    with locks.acquire(scope, locking_port.AcquisitionPolicy.immediate()) as lease:
        for _ in range(3):
            with (
                pytest.raises(errors.Refusal),
                locks.acquire(scope, locking_port.AcquisitionPolicy.immediate()),
            ):
                pass
            assert locks.holder(scope) == lease.holder
