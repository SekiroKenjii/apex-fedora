#!/usr/bin/env python3
"""Capture and replay the observable output of every command.

The restructure must not change what a command prints or which exit code it returns.
This records both against a synthetic runtime root, so a later implementation can be
compared byte for byte after declared normalisation.
"""

from __future__ import annotations

import argparse
import dataclasses
import enum
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Iterator, Sequence
from pathlib import Path

from migration import normalisers, synthetic_root

REPOSITORY = Path(__file__).resolve().parents[2]
GOLDEN_DIRECTORY = REPOSITORY / "tests" / "golden"
ENTRY_POINT = REPOSITORY / "tools" / "apex.py"
TRACER = REPOSITORY / "tools" / "migration" / "effect_trace.py"
INVOCATION_TIMEOUT = 60

class Tier(enum.StrEnum):
    PURE = "pure"
    REFUSAL = "refusal"


@dataclasses.dataclass(frozen=True, slots=True)
class Invocation:
    slug: str
    tier: Tier
    arguments: tuple[str, ...]
    writes_state: bool = False


SUBCOMMANDS = (
    "artifact", "build", "build-nvidia", "builder", "decode-coefficient", "doctor",
    "git-hook", "hardware-snapshot", "hooks", "installer-fixtures", "installer-logs",
    "readiness", "record", "report", "select-candidate", "sources", "test-artifact",
    "test-compare-disks", "test-fingerprint", "test-hotplug-usb", "test-installer-fault",
    "test-installer-fault-collect", "test-installer-trust", "test-live-check",
    "test-power-loss", "test-resume", "test-vm", "trust-development-key", "ventoy-media",
    "verify-artifact",
)

REFUSALS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("unknown-subcommand", ("no-such-command",)),
    ("no-subcommand", ()),
    ("artifact-missing-kind", ("artifact",)),
    ("artifact-unknown-kind", ("artifact", "raw", "--build", "0" * 32)),
    ("artifact-missing-build", ("artifact", "qcow2")),
    ("build-unknown-profile", ("build", "gentoo")),
    ("builder-unknown-action", ("builder", "levitate")),
    ("select-candidate-bad-id",
     ("select-candidate", "--build", "zzz", "--trusted-key", "/dev/null")),
    ("select-candidate-missing-key", ("select-candidate", "--build", "0" * 32)),
    ("verify-artifact-missing-directory",
     ("verify-artifact", "/nonexistent", "--trusted-key", "/dev/null")),
    ("test-vm-missing-disk", ("test-vm",)),
    ("test-live-check-unknown-case", ("test-live-check", "no-such-probe")),
    ("test-installer-fault-unknown-case", ("test-installer-fault", "no-such-fault")),
    ("installer-logs-prepare-with-run", ("installer-logs", "prepare", "--run", "/tmp/x")),
    ("installer-logs-collect-without-token", ("installer-logs", "collect", "--run", "/tmp/x")),
    ("record-unknown-check",
     ("record", "no.such.check", "PASS", "--environment", "vm", "--description", "d")),
    ("record-hardware-from-vm",
     ("record", "audio.speakers", "PASS", "--environment", "vm", "--description", "d")),
    ("record-pass-without-proof",
     ("record", "boot.ten-cycles", "PASS", "--environment", "vm", "--description", "d")),
    ("record-invalid-status",
     ("record", "boot.ten-cycles", "MAYBE", "--environment", "vm", "--description", "d")),
    ("decode-coefficient-missing-operands", ("decode-coefficient", "0x20")),
    ("test-fingerprint-missing-build", ("test-fingerprint",)),
    ("build-nvidia-missing-build", ("build-nvidia",)),
    ("ventoy-media-missing-arguments", ("ventoy-media", "--ubuntu", "/dev/null")),
    ("test-resume-missing-run", ("test-resume",)),
    ("test-compare-disks-missing-run", ("test-compare-disks",)),
    ("test-hotplug-usb-missing-source", ("test-hotplug-usb",)),
    ("test-artifact-missing-key", ("test-artifact", "/nonexistent")),
    ("readiness-blocked", ("readiness",)),
)

VALID_SUBJECT = "fix(audio): initialize the ALC294 speaker amplifier"
INVALID_SUBJECTS = (
    ("commit-msg-too-long", "fix(audio): " + "x" * 80),
    ("commit-msg-unknown-type", "improve(audio): initialize the amplifier"),
    ("commit-msg-missing-colon", "fix(audio) initialize the amplifier"),
    ("commit-msg-with-body", "fix(audio): initialize the amplifier\n\nA body is not allowed.\n"),
    ("commit-msg-with-co-author", "fix(audio): initialize it\n\nCo-authored-by: Someone <a@b.c>\n"),
    ("commit-msg-empty", ""),
)


def invocations() -> Iterator[Invocation]:
    yield Invocation("help-top-level", Tier.PURE, ("--help",))
    for name in SUBCOMMANDS:
        yield Invocation(f"help-{name}", Tier.PURE, (name, "--help"))
    for operands, tier in (
        (("0x20", "0x500", "0x0"), Tier.PURE),
        (("0x20", "0x400", "0xff"), Tier.PURE),
        (("0x20", "0xc00", "0x11"), Tier.PURE),
        (("0x14", "0x3", "0x80"), Tier.REFUSAL),
    ):
        yield Invocation(
            f"decode-coefficient-{operands[1]}-{operands[2]}", tier,
            ("decode-coefficient", *operands),
        )
    yield Invocation("report", Tier.PURE, ("report",))
    yield Invocation("builder-status-absent", Tier.PURE, ("builder", "status"))
    yield Invocation(
        "commit-msg-valid", Tier.PURE, ("git-hook", "commit-msg", "<subject>")
    )
    for slug, _ in INVALID_SUBJECTS:
        yield Invocation(slug, Tier.REFUSAL, ("git-hook", "commit-msg", "<subject>"))
    for slug, arguments in REFUSALS:
        yield Invocation(slug, Tier.REFUSAL, arguments, writes_state=slug.startswith("record-"))


def subject_for(slug: str) -> str:
    for candidate, body in INVALID_SUBJECTS:
        if candidate == slug:
            return body
    return VALID_SUBJECT


def run(invocation: Invocation, root: Path, scratch: Path) -> dict[str, object]:
    arguments = list(invocation.arguments)
    if "<subject>" in arguments:
        message = scratch / f"{invocation.slug}.msg"
        message.write_text(subject_for(invocation.slug))
        arguments[arguments.index("<subject>")] = str(message)
    trace_file = scratch / f"{invocation.slug}.trace.json"
    environment = dict(os.environ)
    environment["APEX_STATE_DIR"] = str(root)
    environment["APEX_EFFECT_TRACE"] = str(trace_file)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["COLUMNS"] = "100"
    # The corpus records what the guard in this tree does. An operator who has exported
    # the fallback switch would otherwise replay all 72 invocations against the older one.
    environment["APEX_GUARD"] = ""
    completed = subprocess.run(
        [sys.executable, str(TRACER), str(ENTRY_POINT), *arguments],
        capture_output=True, text=True, timeout=INVOCATION_TIMEOUT,
        env=environment, cwd=REPOSITORY,
    )

    def normalise(text: str) -> str:
        return normalisers.normalise(text, root=str(root), repository=str(REPOSITORY))

    trace = json.loads(trace_file.read_text()) if trace_file.is_file() else {"events": []}
    effects = [
        json.loads(normalise(json.dumps(event, sort_keys=True))) for event in trace["events"]
    ]
    return {
        "slug": invocation.slug,
        "tier": str(invocation.tier),
        "arguments": list(invocation.arguments),
        "exit_code": completed.returncode,
        "stdout": normalise(completed.stdout),
        "stderr": normalise(completed.stderr),
        "effects": effects,
    }


def capture(root_template: Path, scratch: Path) -> list[dict[str, object]]:
    results = []
    for invocation in invocations():
        root = root_template
        if invocation.writes_state:
            root = scratch / f"root-{invocation.slug}"
            shutil.rmtree(root, ignore_errors=True)
            shutil.copytree(root_template, root)
        results.append(run(invocation, root, scratch))
    return results


def write(results: Sequence[dict[str, object]]) -> None:
    GOLDEN_DIRECTORY.mkdir(parents=True, exist_ok=True)
    target = GOLDEN_DIRECTORY / "commands.json"
    with target.open("w") as handle:
        json.dump({"invocations": list(results)}, handle, indent=1, sort_keys=True)
        handle.write("\n")


def _first_differing_lines(expected: object, observed: object) -> list[str]:
    before = str(expected).splitlines() or [str(expected)]
    after = str(observed).splitlines() or [str(observed)]
    for index in range(max(len(before), len(after))):
        old_line = before[index] if index < len(before) else "<absent>"
        new_line = after[index] if index < len(after) else "<absent>"
        if old_line != new_line:
            return [f"expected: {old_line[:200]}", f"observed: {new_line[:200]}"]
    return []


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["record", "verify"])
    parser.add_argument("--scratch", type=Path, required=True)
    arguments = parser.parse_args(argv)

    scratch = arguments.scratch.expanduser().resolve()
    scratch.mkdir(parents=True, exist_ok=True)
    template = synthetic_root.build(scratch / "template")
    results = capture(template, scratch)

    if arguments.action == "record":
        write(results)
        tiers: dict[str, int] = {}
        for item in results:
            tiers[str(item["tier"])] = tiers.get(str(item["tier"]), 0) + 1
        print(json.dumps({"captured": len(results), "tiers": tiers}, indent=2))
        return 0

    expected = json.loads((GOLDEN_DIRECTORY / "commands.json").read_text())["invocations"]
    differences = [
        {"slug": new["slug"], "field": field, "expected": old[field], "observed": new[field]}
        for old, new in zip(expected, results, strict=True)
        for field in ("exit_code", "stdout", "stderr", "effects")
        if old[field] != new[field]
    ]
    print(json.dumps({"compared": len(results), "differences": len(differences)}, indent=2))
    for difference in differences:
        print(f"  {difference['slug']}: {difference['field']} changed", file=sys.stderr)
        for line in _first_differing_lines(difference["expected"], difference["observed"]):
            print(f"    {line}", file=sys.stderr)
    return 1 if differences else 0


if __name__ == "__main__":
    sys.exit(main())
