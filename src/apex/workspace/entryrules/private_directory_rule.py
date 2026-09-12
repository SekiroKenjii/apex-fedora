"""Directories whose whole contents are local.

Only the components above the file are examined, so a file named `logs` is an ordinary file
while anything under a directory named `logs` is not.

One directory name is both a private one and a package: `agent` holds local material at the
workspace root and is also the program that runs inside a guest. The package form is admitted
only at its two exact homes, directly under `src/apex` and directly under one test tier, and
the name stays private everywhere else.
"""

from __future__ import annotations

from collections.abc import Sequence

from apex.kernel import identifiers, refusals
from apex.workspace import entryrules, ruleorigins, rulespecs

RULE = identifiers.RuleId("repository.private-directory")
DIRECTORIES = frozenset(
    {
        ".claude",
        ".codex",
        ".agents",
        "agent",
        "evidence",
        "private",
        "logs",
        "fprint",
        "fingerprints",
        "__pycache__",
    }
)
PACKAGE_DIRECTORY = "agent"
PACKAGE_HOME = ("src", "apex")
TEST_ROOT = "tests"


def is_package_home(components: tuple[str, ...], index: int) -> bool:
    """Whether the `agent` at `index` is the package or its mirror under a test tier."""
    above = components[:index]
    return above == PACKAGE_HOME or (len(above) == 2 and above[0] == TEST_ROOT)


def _private(components: tuple[str, ...], index: int) -> bool:
    component = components[index]
    if component.lower() not in DIRECTORIES:
        return False
    return not (component == PACKAGE_DIRECTORY and is_package_home(components, index))


def inspect(subject: rulespecs.EntrySubject) -> Sequence[rulespecs.Finding]:
    components = subject.path.directory_components
    offending = [
        component
        for index, component in enumerate(components)
        if _private(components, index)
    ]
    if not offending:
        return ()
    return (
        rulespecs.Finding(
            rule=RULE,
            reason=refusals.RefusalReason.REPOSITORY_PRIVATE_DIRECTORY,
            subject=f"{subject.path.value} is under {offending[0]}",
            remedy="everything below that directory is local to this machine",
        ),
    )


entryrules.declare(
    rulespecs.EntryRule(
        id=RULE,
        origin=ruleorigins.Decomposed(ruleorigins.LegacySurface.PERMITTED),
        inspect=inspect,
    )
)
