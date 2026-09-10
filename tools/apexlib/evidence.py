from __future__ import annotations

import json
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .common import ROOT, Blocked, atomic_json, regular_file, sha256

STATUSES = {"PASS", "FAIL", "BLOCKED", "NOT TESTED"}
DIGEST = re.compile(r"sha256:[0-9a-f]{64}")


def required_checks() -> dict:
    return json.loads((ROOT / "config/checks.json").read_text())


def evaluate(directory: Path, digest: str | None) -> dict:
    records = {}
    errors = []
    evidence_root = (directory / "evidence").resolve()
    if evidence_root.exists():
        for path in sorted(evidence_root.glob("*.json")):
            try:
                record = json.loads(path.read_text())
                check = record["check"]
                required = required_checks()
                if check not in {item for items in required.values() for item in items}:
                    raise ValueError(f'Unknown check ID: {check}')
                if check in records:
                    raise ValueError(f"Duplicate evidence for {check}")
                if record["status"] not in STATUSES:
                    raise ValueError("Invalid result status")
                if not digest or record.get("digest") != digest:
                    raise ValueError(f"Stale or unbound evidence for {check}")
                proof = record.get("proof", [])
                if record["status"] == "PASS" and not proof:
                    raise ValueError(f"PASS needs evidence files: {check}")
                environment = record.get('environment', {})
                if environment.get('kind') not in {'build', 'vm', 'physical', 'operator'} or not environment.get('description'):
                    raise ValueError('Evidence needs an environment kind and description')
                if check in required['hardware'] and environment['kind'] != 'physical':
                    raise ValueError('Hardware evidence must come from physical testing')
                for item in proof:
                    artifact = evidence_root / item["path"]
                    if artifact.is_symlink() or not artifact.resolve().is_relative_to(evidence_root):
                        raise ValueError("Evidence path escapes the evidence directory")
                    if not artifact.is_file() or sha256(artifact) != item["sha256"]:
                        raise ValueError(f"Evidence file missing or changed for {check}")
                records[check] = record
            except (ValueError, KeyError, OSError) as exc:
                errors.append(f"{path.name}: {exc}")
    groups = {}
    for group, checks in required_checks().items():
        groups[group] = {check: records.get(check, {"status": "NOT TESTED", "reason": "No verified result"}) for check in checks}
    ready = bool(digest and DIGEST.fullmatch(digest)) and not errors and all(r["status"] == "PASS" for checks in groups.values() for r in checks.values())
    return {"digest": digest, "ready_to_install": ready, "errors": errors, "checks": groups}


def report(directory: Path) -> dict:
    candidate = directory / "candidate.json"
    digest = json.loads(candidate.read_text()).get("digest") if candidate.exists() else None
    result = evaluate(directory, digest)
    atomic_json(directory / "readiness.json", result)
    return result


def select(directory: Path, candidate: dict):
    """Select an already verified build, retaining the old candidate's evidence."""
    if not DIGEST.fullmatch(candidate.get('digest', '')):
        raise Blocked('Candidate needs a full OCI manifest digest')
    target = directory / 'candidate.json'
    previous = json.loads(regular_file(target, within=directory).read_text()) if target.exists() else None
    evidence = directory / 'evidence'
    if evidence.is_symlink():
        raise Blocked('Evidence storage must not be a symlink')
    if previous and previous.get('digest') != candidate['digest']:
        history = directory / 'candidate-history'
        if history.is_symlink():
            raise Blocked('Candidate history must not be a symlink')
        history.mkdir(exist_ok=True, mode=0o700)
        archive = history / uuid.uuid4().hex
        archive.mkdir(mode=0o700)
        atomic_json(archive / 'candidate.json', previous)
        atomic_json(archive / 'readiness.json', evaluate(directory, previous.get('digest')))
        if evidence.exists():
            evidence.rename(archive / 'evidence')
    elif not previous and evidence.exists():
        raise Blocked('Evidence has no candidate; inspect it before selecting a build')
    atomic_json(target, candidate)
    return report(directory)


def record(directory: Path, check: str, status: str, environment: str, description: str, proofs: list[Path], reason: str):
    candidate = json.loads(regular_file(directory / 'candidate.json', within=directory).read_text())
    if check not in {item for items in required_checks().values() for item in items}:
        raise Blocked('Unknown required check')
    if check in required_checks()['hardware'] and environment != 'physical':
        raise Blocked('Hardware evidence cannot be supplied by a VM')
    if status == 'PASS' and not proofs:
        raise Blocked('PASS needs proof files')
    root = directory / 'evidence'
    root.mkdir(exist_ok=True, mode=0o700)
    capture = root / uuid.uuid4().hex
    capture.mkdir(mode=0o700)
    artifacts = []
    for index, path in enumerate(proofs):
        path = regular_file(path)
        if path.suffix.lower() not in {'.txt', '.log', '.json', '.png', '.ppm', '.xml'}:
            raise Blocked('Use a text, JSON, image or JUnit proof; never store biometric templates')
        target = capture / f'{index}-{path.name}'
        shutil.copyfile(path, target)
        target.chmod(0o600)
        artifacts.append({'path': str(target.relative_to(root)), 'sha256': sha256(target)})
    target = root / f'{check}.json'
    if target.exists():
        history = root / 'history'
        history.mkdir(exist_ok=True, mode=0o700)
        shutil.copyfile(target, history / f'{check}-{uuid.uuid4().hex}.json')
    atomic_json(target, {'check': check, 'digest': candidate['digest'], 'status': status, 'environment': {'kind': environment, 'description': description}, 'recorded_at': datetime.now(timezone.utc).isoformat(), 'reason': reason, 'proof': artifacts})
    return report(directory)
