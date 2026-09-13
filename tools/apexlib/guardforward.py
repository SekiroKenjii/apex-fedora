"""The one place the older tree hands a hook to the repository rules.

The dependency runs one way, from the tree being retired to the tree replacing it, so deleting
this file is the whole of taking the route back.

The property that matters: a commit cannot become permitted because something in the new code
went wrong. Only a refusal from the rules counts as a verdict. Any other exit code, a missing
package, an interpreter too old, or any exception at all is reported and then handed to the guard
that has been deciding until now, which delivers its own verdict. Degrading to the older
implementation is not the same as degrading to nothing.
"""

from __future__ import annotations

import sys
import traceback
from collections.abc import Mapping, Sequence
from pathlib import Path

from apexlib import gitguard

REPOSITORY = Path(__file__).resolve().parents[2]
PACKAGE = REPOSITORY / "src" / "apex" / "__init__.py"
FLOOR = (3, 12)
NOTE = "NOTE: the repository rules did not answer, so the previous guard decided this."


def _unavailable(environment: Mapping[str, str]) -> str:  # noqa: ARG001
    """Why the rules cannot answer, decided before anything can raise.

    Every check here runs before the path is touched and before the package is imported, so
    a missing package or an interpreter that cannot parse it is reported, never raised.
    """
    if sys.version_info[:2] < FLOOR:
        running = ".".join(str(part) for part in sys.version_info[:3])
        needed = ".".join(str(part) for part in FLOOR)
        return f"this hook ran on Python {running}, and the rules need {needed}"
    if not PACKAGE.is_file():
        return f"the rules are not checked out at {PACKAGE.parent}"
    return ""


def _legacy(kind: str, arguments: Sequence[str], standard_input: str) -> None:
    if kind == "pre-commit":
        gitguard.inspect_tree(REPOSITORY)
    elif kind == "commit-msg":
        gitguard.validate_subject(Path(arguments[0]).read_text())
    else:
        gitguard.inspect_outgoing(REPOSITORY, standard_input)


def run(kind: str, arguments: Sequence[str], environment: Mapping[str, str]) -> int:
    standard_input = sys.stdin.read() if kind == "pre-push" else ""
    fault = _unavailable(environment)
    if not fault:
        try:
            sys.path[:0] = [str(REPOSITORY / "src")]
            from apex.cli import hookdispatch, hookkinds
            from apex.kernel import errors

            if kind in hookkinds.names():
                code = hookdispatch.main([kind, *arguments], standard_input)
                if code == errors.Refusal.exit_code:
                    return code
                if code != 0:
                    fault = f"the rules reported exit {code} rather than a verdict"
        except (KeyboardInterrupt, SystemExit):
            raise
        except BaseException:
            fault = f"the rules failed: {traceback.format_exc(limit=0).strip()}"
    if fault:
        print(f"{NOTE} ({fault})", file=sys.stderr)
    _legacy(kind, arguments, standard_input)
    return 0
