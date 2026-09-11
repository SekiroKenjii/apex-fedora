"""Errors typed by what the caller should do about them.

A single exception type cannot distinguish a considered refusal from a typing mistake. These
can, and each carries the exit code that tells the operator which one happened.
"""

from __future__ import annotations

from apex.kernel import refusals

INTERNAL_DEFECT_EXIT_CODE = 70


class ApexError(Exception):
    """Base for every condition this project decides about deliberately."""

    exit_code = 1


class Refusal(ApexError):
    """A rule of the project forbids this. Nothing was attempted."""

    exit_code = 2

    def __init__(
        self, reason: refusals.RefusalReason, *, subject: str, remedy: str = ""
    ) -> None:
        self.reason = reason
        self.subject = subject
        self.remedy = remedy
        detail = f"{reason.value}: {subject}"
        super().__init__(f"{detail}; {remedy}" if remedy else detail)


class PreconditionUnmet(ApexError):
    """The environment is not ready. Report what is missing."""

    exit_code = 3

    def __init__(self, reason: refusals.RefusalReason, *, subject: str) -> None:
        self.reason = reason
        self.subject = subject
        super().__init__(f"{reason.value}: {subject}")


class VerificationFailed(ApexError):
    """Something was checked and did not hold."""

    exit_code = 4

    def __init__(self, *, check: str, expected: str, observed: str) -> None:
        self.check = check
        self.expected = expected
        self.observed = observed
        super().__init__(f"{check}: expected {expected}, observed {observed}")


class PortFailure(ApexError):
    """An external tool or the host failed."""

    exit_code = 5

    def __init__(self, *, port: str, cause: str) -> None:
        self.port = port
        self.cause = cause
        super().__init__(f"{port}: {cause}")


class RegistrationError(ApexError):
    """A unit is declared inconsistently. Raised while sealing, before anything runs."""

    exit_code = 6


class InternalDefect(Exception):
    """A bug. Never caught, never reported as a considered decision."""
