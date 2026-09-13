"""Every tracked file judged by the repository's entry and content rules, the hook's own.

The hooks judge what a commit stages and what a push sends; this judges the whole index,
so a file that slipped in before a rule existed is found, and the organisation-name rule
holds over every tracked file and not only the changed ones.
"""

from __future__ import annotations

from apex.workspace import checks, gitguarding, gitreading, treejudging


def run(site: checks.Site) -> checks.Outcome:
    rows = gitreading.staged_rows(site.processes, site.repository)
    names = sorted({row.object_name for row in rows if row.mode.carries_blob})
    sizes = gitreading.sizes(site.processes, site.repository, names)
    contents = gitreading.contents(
        site.processes, site.repository, treejudging.readable(rows, sizes)
    )
    findings = treejudging.judge_rows(
        rows,
        sizes=sizes,
        contents=contents,
        entry_rules=gitguarding.registered_entry_rules(),
        content_rules=gitguarding.registered_content_rules(),
    )
    if not findings:
        return checks.Outcome(status=checks.PASS, detail=f"{len(rows)} tracked entries judged")
    lines = [f"{finding.rule}: {finding.subject}: {finding.reason}" for finding in findings]
    return checks.Outcome(status=checks.FAIL, detail=checks.tail("\n".join(lines)))


checks.declare(
    checks.Check(
        id="tree",
        summary="every tracked file satisfies the repository's entry and content rules",
        order=90,
        run=run,
    )
)
