#!/usr/bin/env python3
"""Build a deterministic runtime root that reproduces every stored v1 shape.

The golden corpus must not depend on the operator's real runtime root, which changes
whenever a test runs. This builds an equivalent root from fixed identifiers and fixed
timestamps, so the same input always produces the same bytes.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import shutil
import sys
from collections.abc import Sequence
from pathlib import Path

DIGEST = "sha256:2daf0bc614838352a65af743e2e0efb658e040169dd95e25520eb1334f42c912"
SUPERSEDED_DIGEST = "sha256:f2cbb445bca4dfdc43dbccb025b59c633137464d3f1fddab83e402617cb296de"
BUILD_ID = "ee97157d34b9480186730786268f6a0c"
SUPERSEDED_BUILD_ID = "ec28594d17594c98b7253a09f28691b2"
TRUSTED_KEY_DIGEST = "e85e0708a0d19e7002504835de342fbb7fa03c510c9fef4161f74a13838b2afd"
RECORDED_AT = "2026-09-08T14:29:48.549782+00:00"
SUPERSEDED_AT = "2026-09-07T09:11:02.100000+00:00"


@dataclasses.dataclass(frozen=True, slots=True)
class Record:
    check: str
    status: str
    environment_kind: str
    description: str
    reason: str
    capture: str | None = None
    proofs: tuple[tuple[str, str], ...] = ()
    corrupt_proof: bool = False


RECORDS: tuple[Record, ...] = (
    Record(
        "boot.ten-cycles",
        "PASS",
        "vm",
        "Ten offline boots of the frozen private QCOW2",
        "Normal boots only; no claim of failed-deployment recovery.",
        capture="0dff0c4156f3476cafc5decf611fa714",
        proofs=(("0-summary.json", '{"boots": 10}\n'), ("1-application.png", "PNGDATA\n")),
    ),
    Record(
        "signature.accept",
        "PASS",
        "build",
        "Signed bundle verified against the development key",
        "Development signing only.",
        capture="23a1dbc1824547eba44ab97cbda930e7",
        proofs=(("0-results.json", '{"verified": 58}\n'),),
    ),
    Record(
        "audio.speakers",
        "BLOCKED",
        "physical",
        "Prior user report of ALC294 speaker failure on this laptop",
        "The reported fault is unresolved.",
    ),
    Record(
        "desktop.theme-surfaces",
        "FAIL",
        "vm",
        "Screenshot review found a light GTK3 window",
        "GTK3 falls back to light Adwaita without the dark alias.",
        capture="30dca8f7493546a48083fdc780c70c6e",
        proofs=(("0-review.json", '{"opaque": false}\n'),),
    ),
    Record(
        "live.direct",
        "PASS",
        "vm",
        "Direct UEFI live boot with disk protection observed",
        "Scoped to this operational VM.",
        capture="32f33b2ff9114b038a2e6e53bf29972a",
        proofs=(("0-probe.json", '{"read_only": true}\n'),),
        corrupt_proof=True,
    ),
)

HISTORICAL = Record(
    "boot.ten-cycles",
    "FAIL",
    "vm",
    "An earlier ten-boot attempt that failed on boot four",
    "Superseded by the passing run.",
)


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with path.open("w") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")
    path.chmod(0o600)


def record_document(record: Record, digest: str, recorded_at: str, root: Path) -> dict[str, object]:
    proofs: list[dict[str, str]] = []
    if record.capture:
        capture = root / "evidence" / record.capture
        capture.mkdir(parents=True, exist_ok=True, mode=0o700)
        for index, (name, body) in enumerate(record.proofs):
            target = capture / name
            target.write_text(body)
            target.chmod(0o600)
            stored = body
            if record.corrupt_proof and index == 0:
                stored = body.replace("true", "false")
            proofs.append(
                {
                    "path": f"{record.capture}/{name}",
                    "sha256": hashlib.sha256(stored.encode()).hexdigest(),
                }
            )
    return {
        "check": record.check,
        "digest": digest,
        "status": record.status,
        "environment": {"kind": record.environment_kind, "description": record.description},
        "recorded_at": recorded_at,
        "reason": record.reason,
        "proof": proofs,
    }


def candidate_document(digest: str, build_id: str) -> dict[str, object]:
    return {
        "digest": digest,
        "build_id": build_id,
        "verification": {
            "status": "PASS",
            "digest": digest,
            "purpose": "development-only",
            "trusted_key_sha256": TRUSTED_KEY_DIGEST,
            "files_verified": 58,
            "bootc_update_policy": "NOT TESTED",
        },
    }


def build(root: Path) -> Path:
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, mode=0o700)

    write_json(root / "candidate.json", candidate_document(DIGEST, BUILD_ID))
    for record in RECORDS:
        document = record_document(record, DIGEST, RECORDED_AT, root)
        write_json(root / "evidence" / f"{record.check}.json", document)

    history = record_document(HISTORICAL, DIGEST, SUPERSEDED_AT, root)
    write_json(
        root / "evidence" / "history" / f"{HISTORICAL.check}-4a24fbbec73d49ca9e7604cf9e965419.json",
        history,
    )

    archive = root / "candidate-history" / "33362be7ef014d39b4fb803d9f485fe8"
    write_json(
        archive / "candidate.json", candidate_document(SUPERSEDED_DIGEST, SUPERSEDED_BUILD_ID)
    )
    write_json(archive / "readiness.json", {"digest": SUPERSEDED_DIGEST, "ready_to_install": False})
    plain = dataclasses.replace(RECORDS[1], capture=None, proofs=())
    archived = record_document(plain, SUPERSEDED_DIGEST, SUPERSEDED_AT, root)
    write_json(archive / "evidence" / f"{RECORDS[1].check}.json", archived)

    export = root / "exports" / BUILD_ID
    write_json(export / "result.json", {"status": "PASS", "kind": "image", "digest": DIGEST})
    (export / "output").mkdir(parents=True, exist_ok=True, mode=0o700)

    trust = root / "trust"
    trust.mkdir(parents=True, exist_ok=True, mode=0o700)
    (trust / "development.pub").write_text("ssh-ed25519 AAAA-synthetic development\n")
    (trust / "development.pub").chmod(0o600)
    return root


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", type=Path)
    arguments = parser.parse_args(argv)
    root = build(arguments.target.expanduser().resolve())
    print(json.dumps({"root": str(root), "records": len(RECORDS)}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
