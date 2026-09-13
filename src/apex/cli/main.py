"""Entry point for the installed console script."""

from __future__ import annotations

import os
import sys
from collections.abc import Sequence

from apex.cli import dispatch
from apex.wiring import hostbundle


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    return dispatch.run(
        arguments,
        context_of=lambda: hostbundle.context(os.environ),
        stdout=sys.stdout,
        stderr=sys.stderr,
    )


if __name__ == "__main__":
    sys.exit(main())
