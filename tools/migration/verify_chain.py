#!/usr/bin/env python3
"""Replay the attestation chain and name the first entry that does not hold.

The chain is empty until minting starts writing to it, and an empty chain is a true answer
rather than a skipped check. Running this on every gate keeps the reader exercised instead of
leaving it to be discovered at the moment it is needed.

The key sits beside the chain under the same account, laid down when the store was first
opened for writing; before that, an environment variable may name one. A broken link
therefore means an edit made without the key or a file damaged by something else, not proof
that the operator did not change the chain deliberately.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPOSITORY / "src")]

from apex.adapters.real import real_files  # noqa: E402
from apex.attestation import ledger, proofs  # noqa: E402
from apex.kernel import safepaths, secrets  # noqa: E402

KEY_VARIABLE = "APEX_CHAIN_KEY"


def inspect(root: Path, key: str) -> dict[str, object]:
    location = proofs.StoreLocation(root=safepaths.RuntimeRoot.adopt(root))
    files = real_files.LocalFiles()
    lines, head = ledger.read_chain(location, files)
    signer = ledger.signer_at(location, files) or ledger.ChainSigner(secrets.Secret(key))
    report = ledger.replay(lines, signer=signer, head=head)
    return {
        "entries": report.entries,
        "intact": report.intact,
        "first_break": (
            None
            if report.first_break is None
            else {
                "sequence": report.first_break.sequence,
                "cause": str(report.first_break.cause),
            }
        ),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=None)
    arguments = parser.parse_args(argv)
    root = (arguments.root or Path("~/.local/share/apex-fedora/runtime")).expanduser()
    if not root.is_dir():
        print(json.dumps({"skipped": "no runtime root on this machine"}, indent=2))
        return 0
    result = inspect(root, os.environ.get(KEY_VARIABLE, ""))
    print(json.dumps(result, indent=2))
    if not result["intact"]:
        print("The attestation chain is broken", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
