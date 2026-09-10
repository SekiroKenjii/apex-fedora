"""Entry point for the installed console script."""

from __future__ import annotations

import sys
from collections.abc import Sequence

from apex.cli import legacy_bridge


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    return legacy_bridge.dispatch(arguments)


if __name__ == "__main__":
    sys.exit(main())

