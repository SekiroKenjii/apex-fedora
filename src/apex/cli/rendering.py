"""Table to text.

Presentation sits in the presentation layer, so the projection can be tested without a
rendering and the rendering without a store.
"""

from __future__ import annotations

from apex.attestation import columns

HEADINGS = ("CHECK", "VERDICT", "ORIGIN", "IMPORT LIMITS")
GAP = "  "
WITHHELD_NOTE = "withheld"
FAULTS_HEADING = "FAULTS"


def _cells(row: columns.Row) -> tuple[str, str, str, str]:
    return (
        row.check,
        row.verdict.stored_name,
        str(row.origin),
        ", ".join(str(limit) for limit in row.limits),
    )


def render(table: columns.Table) -> str:
    body = [_cells(row) for row in table.rows]
    widths = [
        max(len(heading), *(len(cells[index]) for cells in body)) if body else len(heading)
        for index, heading in enumerate(HEADINGS)
    ]
    lines = [
        f"store version {table.version}, "
        f"{'strict' if table.strict else 'default'} readiness",
        GAP.join(heading.ljust(widths[index]) for index, heading in enumerate(HEADINGS)),
    ]
    for row, cells in zip(table.rows, body, strict=True):
        line = GAP.join(cell.ljust(widths[index]) for index, cell in enumerate(cells))
        if row.withheld is not None:
            line = f"{line}{GAP}({WITHHELD_NOTE} {row.withheld.stored_name})"
        lines.append(line.rstrip())
    if table.faults:
        lines.append(FAULTS_HEADING)
        lines.extend(f"{GAP}{fault}" for fault in table.faults)
    counted = ", ".join(f"{name} {count}" for name, count in sorted(table.counts.items()))
    lines.append(f"{counted}; imported {table.imported}; ready {table.ready}")
    return "\n".join(lines) + "\n"
