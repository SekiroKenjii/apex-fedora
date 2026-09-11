#!/usr/bin/env python3
"""Compare the new repository rules with the guard they will eventually replace.

The old guard is a working control. It refused a real commit during this restructure, which is
why one package in this project is named the way it is. So the rules that replace it are held to
a relation, checked on real data, before anything is repointed at them.

Two configurations are compared, and they assert different things.

The transcribed rules must agree with the old guard in BOTH directions. Those rules claim only
to restate refusals that already exist, so any difference either way is a transcription error.

The full rule set must never PERMIT anything the old guard refuses. It may refuse more, but only
where a rule that declares itself an addition is the one that fired, and that rule carries its
own reason for existing. There is no list of blessed exceptions anywhere: the justification
lives on the rule, so adding a deliberate new refusal stays one new file.

Read only. Nothing here writes to the repository or to any runtime root.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPOSITORY / "src"), str(REPOSITORY / "tools")]

from apex.kernel import quantities, treerows  # noqa: E402
from apex.workspace import gitguarding, ruleorigins, rulespecs  # noqa: E402
from apexlib import gitguard as legacy  # noqa: E402

MODE_FOR_PATH_CASES = treerows.EntryMode.REGULAR
BENIGN = b"value = 1\n"
OVERSIZE = 20 * 1024 * 1024 + 1
SAMPLE_PATHS = ("helper.py", "docs/guide.md", "tools/run.sh")
CASE_FORMS = ("as-is", "lower", "upper", "title")
DEPTHS = (0, 1, 3)
# Ten characters whose case folding reaches ASCII where lowering does not. A rule that folded
# would refuse paths the old guard permits, which is a difference in the direction the oracle
# treats as a transcription error.
FOLD_DIVERGENT = ("ß", "ſ", "ẞ", "ﬀ", "ﬁ", "ﬂ", "ﬃ", "ﬄ", "ﬅ", "ﬆ")


def git(*arguments: str) -> str:
    return subprocess.run(
        ["git", "-C", str(REPOSITORY), *arguments],
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def tracked_paths() -> set[str]:
    history = git("log", "--all", "--pretty=format:", "--name-only").splitlines()
    index = [
        row.split("\t", 1)[1]
        for row in git("ls-files", "--stage").splitlines()
        if "\t" in row
    ]
    return {name for name in [*history, *index] if name}


def enumerated_paths() -> set[str]:
    """Every shape the old guard can tell apart, generated from its own constants.

    Reading the sets off the module being replaced rather than off the new rules is deliberate.
    A name dropped during transcription would otherwise drop its own test case with it.
    """
    seeds: list[str] = [
        *legacy.PRIVATE_NAMES,
        *legacy.PRIVATE_DIRS,
        *(f"a{suffix}" for suffix in (".log", ".key", ".pem", ".pyc", ".fpt", ".iso")),
        "credentials.json",
        "passphrase",
        "builder_ed25519",
        "token",
        ".netrc",
        ".env.local",
        ".envrc",
        "README.md",
        "helper.py",
        "x.tar.gz",
        "..",
        ".",
        "",
        "a\\b.txt",
        *(f"agent{character}.md" for character in FOLD_DIVERGENT),
    ]
    generated: set[str] = set()
    for seed in seeds:
        for form in CASE_FORMS:
            cased = {
                "as-is": seed,
                "lower": seed.lower(),
                "upper": seed.upper(),
                "title": seed.title(),
            }[form]
            for depth in DEPTHS:
                prefix = "/".join(f"d{index}" for index in range(depth))
                joined = f"{prefix}/{cased}" if prefix else cased
                generated.add(joined)
                generated.add(f"/{joined}")
                generated.add(f"{joined}/child.txt")
    return generated


@dataclasses.dataclass(frozen=True, slots=True)
class Case:
    """One row as the old guard sees it: a path, a mode, and the bytes behind it."""

    path: str
    mode: treerows.EntryMode
    payload: bytes

    @property
    def label(self) -> str:
        return f"{self.path} [{self.mode.value}, {len(self.payload)}B]"


def old_refuses(case: Case) -> bool:
    """Whether the guard being replaced would stop this row.

    An untyped raise counts as a refusal, because the entry point catches those and reports
    them to the operator exactly as it reports a deliberate one.
    """
    try:
        legacy.inspect_blob(case.path, case.mode.value, case.payload)
    except (legacy.Blocked, ValueError, TypeError):
        return True
    return False


def new_findings(
    case: Case,
    *,
    entry_rules: Sequence[rulespecs.EntryRule],
    content_rules: Sequence[rulespecs.ContentRule],
) -> tuple[rulespecs.Finding, ...]:
    path = treerows.RepoPath(case.path)
    findings = gitguarding.judge_entry(
        rulespecs.EntrySubject(
            path=path, mode=case.mode, size=quantities.ByteCount(len(case.payload))
        ),
        rules=entry_rules,
    )
    if not case.mode.carries_blob:
        return findings
    return findings + gitguarding.judge_content(
        rulespecs.ContentSubject(path=path, payload=case.payload), rules=content_rules
    )


def introduced_only(findings: Sequence[rulespecs.Finding], *, origins: dict[str, object]) -> bool:
    return bool(findings) and all(
        isinstance(origins[str(finding.rule)], ruleorigins.Introduced) for finding in findings
    )


def compare(rows: Sequence[Case]) -> dict[str, object]:
    every = gitguarding.registered_entry_rules()
    content = gitguarding.registered_content_rules()
    transcribed_entry = gitguarding.transcribed(every)
    transcribed_content = gitguarding.transcribed(content)
    origins: dict[str, ruleorigins.RuleOrigin] = {
        str(rule.id): rule.origin for rule in [*every, *content]
    }

    weakenings: list[str] = []
    transcription_differences: list[dict[str, str]] = []
    strengthenings: list[dict[str, str]] = []
    unattributed: list[str] = []
    sole = dict.fromkeys(origins, 0)
    fired = dict.fromkeys(origins, 0)

    for row in rows:
        refused = old_refuses(row)
        full = new_findings(row, entry_rules=every, content_rules=content)
        only = new_findings(
            row, entry_rules=transcribed_entry, content_rules=transcribed_content
        )

        if refused and not full:
            weakenings.append(row.label)
        if refused != bool(only):
            transcription_differences.append(
                {
                    "row": row.label,
                    "old": "refuse" if refused else "permit",
                    "transcribed": "refuse" if only else "permit",
                    "rules": ",".join(sorted(str(f.rule) for f in only)),
                }
            )
        if not refused and full:
            strengthenings.append(
                {"row": row.label, "rules": ",".join(sorted(str(f.rule) for f in full))}
            )
            if not introduced_only(full, origins=origins):
                unattributed.append(row.label)
        for finding in full:
            fired[str(finding.rule)] += 1
        if len(full) == 1:
            sole[str(full[0].rule)] += 1

    return {
        "cases": len(rows),
        "weakenings": weakenings,
        "transcription_differences": transcription_differences,
        "strengthenings": len(strengthenings),
        "strengthened_rows": strengthenings[:10],
        "unattributed": unattributed,
        "inert_rules": sorted(name for name, count in fired.items() if count == 0),
        "sole_finding_counts": dict(sorted(sole.items())),
        "finding_counts": dict(sorted(fired.items())),
    }


def self_test(rows: Sequence[Case]) -> dict[str, object]:
    """Removing any transcribed rule must show up as a weakening.

    Without this leg, a mis-specified comparison reports zero differences over a rule set that
    has stopped refusing things, and the gate goes green on a lie.
    """
    every = gitguarding.registered_entry_rules()
    content = gitguarding.registered_content_rules()
    undetectable: list[str] = []
    for removed in [*gitguarding.transcribed(every), *gitguarding.transcribed(content)]:
        thinner_entry = tuple(rule for rule in every if rule.id != removed.id)
        thinner_content = tuple(rule for rule in content if rule.id != removed.id)
        exposed = any(
            old_refuses(row)
            and not new_findings(row, entry_rules=thinner_entry, content_rules=thinner_content)
            for row in rows
        )
        if not exposed:
            undetectable.append(str(removed.id))
    return {"undetectable_rules": sorted(undetectable)}


def payload_classes() -> dict[str, bytes]:
    """One representative of every content shape the old guard decides differently about."""
    return {
        "benign": BENIGN,
        "pem": b"-----BEGIN " + b"OPENSSH PRIVATE KEY-----\n",
        "forge-token": b"ghp_" + b"a" * 36 + b"\n",
        "nul": b"opaque\x00sensor\x01data",
        # No zero byte, or the two binary rules always fire together and neither
        # can be shown to be doing anything on its own.
        "undecodable": b"\xff\xfe\xfd",
        "local-only": b"<!-- apex-" + b"local-only -->\n",
        "oversize": b"x" * OVERSIZE,
        # The organisation name is assembled so this file does not refuse itself. One form is
        # the bare name, which the added rule refuses; the other is the one package coordinate
        # it permits, which must stay permitted by both guards.
        "vendor-name": b"published by " + b"Goo" + b"gle" + b"\n",
        "vendor-coordinate": b"dnf install " + b"goo" + b"gle" + b"-noto-sans-cjk-fonts\n",
    }


def cases() -> list[Case]:
    """Three populations, sized so each rule can fire without a needless cross product.

    Paths carry the path rules, modes carry the shape rules, and payloads carry the content
    rules. Crossing all three would multiply the corpus without reaching a rule that the three
    populations do not already reach on their own.
    """
    built = [
        Case(path, MODE_FOR_PATH_CASES, BENIGN)
        for path in sorted(tracked_paths() | enumerated_paths())
    ]
    built += [
        Case(path, mode, BENIGN)
        for path in SAMPLE_PATHS
        for mode in treerows.EntryMode
        if mode is not MODE_FOR_PATH_CASES
    ]
    built += [
        Case(path, MODE_FOR_PATH_CASES, payload)
        for path in SAMPLE_PATHS
        for name, payload in payload_classes().items()
        if name != "benign"
    ]
    return built


MESSAGE_TYPES = (
    "feat", "fix", "docs", "style", "refactor", "perf", "test", "build", "ci", "chore",
    "revert", "nope",
)
MESSAGE_SCOPES = ("", "(cli)", "(CLI)", "()", "(1x)")
MESSAGE_TAILS = (
    "",
    "\n\nprose body",
    "\n\nBREAKING CHANGE: it moved",
    "\n\nSigned-off-by: someone",
    "\n\nCo-authored-by: someone",
    "\n\nCO-AUTHORED-BY: someone",
    "\r",
)
MESSAGE_LENGTHS = (0, 1, 40, 66, 67, 200)


def messages() -> list[str]:
    """Every shape the declared message policy can tell apart."""
    built: set[str] = set()
    for kind in MESSAGE_TYPES:
        for scope in MESSAGE_SCOPES:
            for length in MESSAGE_LENGTHS:
                subject = f"{kind}{scope}: {'a' * length}"
                for tail in MESSAGE_TAILS:
                    built.add(f"{subject}{tail}\n")
    built.update(
        {
            "\n",
            "\r\n",
            "fix: hello\r\n",
            "fix: a\rb\n",
            "fix: hello\n\n",
            # One line, matching, well inside the width: the only thing wrong is the trailer,
            # which is the one shape that shows that rule deciding on its own.
            "fix: Co-authored-by: someone\n",
        }
    )
    return sorted(built)


def old_refuses_message(raw: str) -> bool:
    try:
        legacy.validate_subject(raw)
    except (legacy.Blocked, ValueError, TypeError):
        return True
    return False


def compare_messages(raws: Sequence[str]) -> dict[str, object]:
    rules = gitguarding.registered_message_rules()
    transcribed = gitguarding.transcribed(rules)
    origins: dict[str, ruleorigins.RuleOrigin] = {str(rule.id): rule.origin for rule in rules}
    differences: list[dict[str, str]] = []
    reported: dict[str, frozenset[str]] = {}
    for raw in raws:
        refused = old_refuses_message(raw)
        subject = rulespecs.MessageSubject(raw)
        found = gitguarding.judge_message(subject, rules=transcribed)
        reported[raw] = frozenset(str(finding.rule) for finding in found)
        if refused != bool(found):
            differences.append(
                {
                    "message": repr(raw),
                    "old": "refuse" if refused else "permit",
                    "transcribed": "refuse" if found else "permit",
                }
            )
    return {
        "messages": len(raws),
        "message_differences": differences[:10],
        "message_difference_count": len(differences),
        "inert_message_rules": sorted(
            name
            for name in origins
            if all(name not in fired for fired in reported.values())
        ),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    arguments = parser.parse_args(argv)
    rows = cases()
    result = compare(rows)
    result.update(compare_messages(messages()))
    if arguments.self_test:
        result["self_test"] = self_test(rows)
        result["rules_undetectable_by_the_corpus"] = result["self_test"]["undetectable_rules"]
    print(json.dumps(result, indent=2, ensure_ascii=True))
    failed = (
        result["weakenings"]
        or result["transcription_differences"]
        or result["unattributed"]
        or result["inert_rules"]
        or result.get("rules_undetectable_by_the_corpus")
        or result["message_difference_count"]
        or result["inert_message_rules"]
    )
    if failed:
        print("The new rules are not equivalent to the guard they replace", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
