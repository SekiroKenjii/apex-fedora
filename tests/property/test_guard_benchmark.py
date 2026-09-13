"""The guard over two thousand staged files stays under three seconds.

The specification's table names the threshold. The rows are parsed as the hook parses the
index, and every registered entry rule and content rule runs over every file with a kilobyte
of ordinary text, which is the whole judgement the hook makes before it lets a commit through.
"""

from __future__ import annotations

import time

import pytest

from apex.kernel import quantities, treerows
from apex.workspace import gitguarding, rulespecs, staging

FILES = 2_000
SECONDS = 3.0
PAYLOAD = b"# a line of ordinary source text that the content rules read\n" * 16

pytestmark = pytest.mark.benchmark


def index_listing() -> bytes:
    rows = []
    for index in range(FILES):
        name = f"src/apex/package{index % 40}/module{index}.py".encode()
        rows.append(b"100644 " + (b"%040x" % index) + b" 0\t" + name + b"\0")
    return b"".join(rows)


def test_two_thousand_staged_files_are_judged_under_the_threshold() -> None:
    raw = index_listing()
    entry_rules = gitguarding.registered_entry_rules()
    content_rules = gitguarding.registered_content_rules()

    started = time.perf_counter()
    rows = staging.index_rows(raw)
    findings: list[rulespecs.Finding] = []
    for row in rows:
        entry = rulespecs.EntrySubject(
            path=row.path, mode=row.mode, size=quantities.ByteCount(len(PAYLOAD))
        )
        findings.extend(gitguarding.judge_entry(entry, rules=entry_rules))
        content = rulespecs.ContentSubject(path=row.path, payload=PAYLOAD)
        findings.extend(gitguarding.judge_content(content, rules=content_rules))
    elapsed = time.perf_counter() - started

    assert len(rows) == FILES
    assert findings == []
    assert elapsed < SECONDS, f"{elapsed:.2f}s for {FILES} files"
    assert isinstance(rows[0].mode, treerows.EntryMode)
