"""Time as a value, so waiting can be driven by a fake clock."""

from __future__ import annotations

import dataclasses

from apex.kernel import errors, refusals


@dataclasses.dataclass(frozen=True, slots=True, order=True)
class Instant:
    seconds: float


@dataclasses.dataclass(frozen=True, slots=True, order=True)
class Elapsed:
    seconds: float

    def __post_init__(self) -> None:
        if self.seconds < 0:
            raise errors.Refusal(
                refusals.RefusalReason.NEGATIVE_QUANTITY, subject=f"{self.seconds}s"
            )


@dataclasses.dataclass(frozen=True, slots=True)
class Deadline:
    budget: Elapsed
    started: Instant = Instant(0)

    def expired_at(self, now: Instant) -> bool:
        return now.seconds - self.started.seconds > self.budget.seconds


@dataclasses.dataclass(frozen=True, slots=True)
class Backoff:
    first: Elapsed
    ceiling: Elapsed
    factor: float

    @classmethod
    def exponential(cls, *, first: Elapsed, ceiling: Elapsed, factor: float) -> Backoff:
        return cls(first=first, ceiling=ceiling, factor=factor)

    def delay(self, attempt: int) -> Elapsed:
        grown = self.first.seconds * (self.factor**attempt)
        return Elapsed(min(grown, self.ceiling.seconds))


@dataclasses.dataclass(frozen=True, slots=True)
class WaitPolicy:
    deadline: Deadline
    backoff: Backoff
    description: str

    def __post_init__(self) -> None:
        if not self.description:
            raise errors.RegistrationError(
                "WaitPolicy: say what condition is being waited for"
            )
