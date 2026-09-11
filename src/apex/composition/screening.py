"""The repository rules, applied to every file before it enters a bundle.

The same rules that guard a commit guard a build input, so a file the hooks would refuse
cannot reach the builder by another door.
"""

from __future__ import annotations

from apex.kernel import errors, quantities, treerows
from apex.ports import archives
from apex.workspace import gitguarding, rulespecs

EXECUTABLE = quantities.FileMode(0o755)


def _mode_of(candidate: archives.BundleCandidate) -> treerows.EntryMode:
    if candidate.mode == EXECUTABLE:
        return treerows.EntryMode.EXECUTABLE
    return treerows.EntryMode.REGULAR


def screen(candidate: archives.BundleCandidate) -> None:
    path = treerows.RepoPath(candidate.path)
    findings = gitguarding.judge_entry(
        rulespecs.EntrySubject(
            path=path,
            mode=_mode_of(candidate),
            size=quantities.ByteCount(len(candidate.payload)),
        ),
        rules=gitguarding.registered_entry_rules(),
    ) + gitguarding.judge_content(
        rulespecs.ContentSubject(path=path, payload=candidate.payload),
        rules=gitguarding.registered_content_rules(),
    )
    if not findings:
        return
    first = findings[0]
    raise errors.Refusal(
        first.reason, subject=f"{candidate.path}: {first.subject}", remedy=first.remedy
    )
