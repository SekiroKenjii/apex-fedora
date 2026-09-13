"""Running the entry and content rules over the rows of one tree or index.

Every row is judged by its path, mode and size; only a row that carries a blob whose bytes
were read is judged by its content, so an oversize object is refused by size without its
bytes ever crossing the port. The findings of one tree come back together, for one report.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from apex.config import defaults
from apex.kernel import quantities
from apex.workspace import gitguarding, rulespecs, staging


def judge_rows(
    rows: Sequence[staging.Row],
    *,
    sizes: Mapping[str, quantities.ByteCount],
    contents: Mapping[str, bytes],
    entry_rules: Sequence[rulespecs.EntryRule],
    content_rules: Sequence[rulespecs.ContentRule],
) -> tuple[rulespecs.Finding, ...]:
    findings: list[rulespecs.Finding] = []
    for row in rows:
        findings.extend(gitguarding.judge_entry(
            rulespecs.EntrySubject(path=row.path, mode=row.mode, size=sizes.get(row.object_name)),
            rules=entry_rules,
        ))
        payload = contents.get(row.object_name)
        if row.mode.carries_blob and payload is not None:
            findings.extend(gitguarding.judge_content(
                rulespecs.ContentSubject(path=row.path, payload=payload), rules=content_rules
            ))
    return tuple(findings)


def readable(
    rows: Sequence[staging.Row], sizes: Mapping[str, quantities.ByteCount]
) -> tuple[str, ...]:
    """The blobs worth reading: those the size rule would not refuse anyway, once each."""
    limit = defaults.SOURCE_BLOB_LIMIT
    seen: dict[str, None] = {}
    for row in rows:
        size = sizes.get(row.object_name)
        if row.mode.carries_blob and size is not None and size.value <= limit.value:
            seen.setdefault(row.object_name, None)
    return tuple(seen)
