"""How a refusal reads when a git hook is the thing refusing.

The guard being replaced raises on the first failure, so a message carrying four separate faults
is reported as one. These rules report all of them, which means the renderer has to say several
things without burying the one the operator needs.

`BLOCKED: ` stays the first token. It is the signal the operator has learned and the only prefix
anything in this tree consumes, so the error kind is distinguished by the exit code the taxonomy
already assigns rather than by inventing a second prefix.
"""

from __future__ import annotations

from collections.abc import Sequence

from apex.workspace import rulespecs

PREFIX = "BLOCKED: "
INDENT = "  "
SUBJECT_LIMIT = 120
ELLIPSIS = "..."
REPORT_LIMIT = 20
ESCAPES = (("\\", "\\\\"), ("\n", "\\n"), ("\r", "\\r"))


def flattened(subject: str) -> str:
    """One line, always.

    A subject carrying a newline would otherwise split one refusal into what looks like two, and
    the second half would not carry the prefix.
    """
    text = subject
    for character, replacement in ESCAPES:
        text = text.replace(character, replacement)
    if len(text) > SUBJECT_LIMIT:
        return text[: SUBJECT_LIMIT - len(ELLIPSIS)] + ELLIPSIS
    return text


def _line(finding: rulespecs.Finding) -> str:
    stated = f"{finding.rule}: {flattened(finding.subject)}"
    return f"{stated}; {finding.remedy}" if finding.remedy else stated


def report(findings: Sequence[rulespecs.Finding], *, subject: str, footer: str = "") -> str:
    """Sorted by rule, so what the operator reads never depends on import order."""
    ordered = sorted(findings, key=lambda finding: str(finding.rule))
    if len(ordered) == 1:
        body = [f"{PREFIX}{_line(ordered[0])}"]
    else:
        body = [f"{PREFIX}{len(ordered)} rules refuse {subject}"]
        body += [f"{INDENT}{_line(item)}" for item in ordered[:REPORT_LIMIT]]
        if len(ordered) > REPORT_LIMIT:
            body.append(f"{INDENT}and {len(ordered) - REPORT_LIMIT} more, not listed")
    if footer:
        body.append(footer)
    return "\n".join(body) + "\n"
