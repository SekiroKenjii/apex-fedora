"""The unit and the older shell run the same programs, in order, and leave the same files.

The older `fingerprint-tests.sh` runs under bash with every program it calls stood in for by
a script that records its arguments and answers from the same spec the unit's fakes answer
from. The unit runs over the real file and engine adapters on that same scripted process.
The argument vectors must agree once the work directory is normalised and the steps that
moved to the host, the downloads and their checksums, are set aside; the files both leave
must be equal, and both must reach the same judgement.
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fingerprintfixtures import BASE, BODIES, FROZEN, IMAGE_ID, Builder, BuilderSpec, lock_document

from apex.adapters.fakes import fake_blockdevices, fake_clock, fake_extents, fake_ids
from apex.adapters.real import real_archives, real_containers, real_digesting, real_files
from apex.agent import agentports, builder
from apex.agent.units import fingerprint_cleanup_unit
from apex.config import defaults

REPOSITORY = Path(__file__).resolve().parents[2]
OLDER_SCRIPT = REPOSITORY / "guest" / "fingerprint-tests.sh"
VAR_TMP = Path("/var/tmp")
STUBBED = (
    "id", "cat", "systemd-detect-virt", "podman", "dnf5", "rpm", "curl", "chown", "timeout",
    "runuser",
)
HOST_SIDE = {"id", "cat", "systemd-detect-virt", "timeout", "curl"}
RELATIVE = {
    "output/fingerprint": "WORK/output/fingerprint",
    "fingerprint-sources": "WORK/fingerprint-sources",
    "guest/test-fingerprint.py": "WORK/test-fingerprint.py",
}
EVIDENCE = ("target-rpms.txt", "test-rpms.txt", "environment-rpms.txt")
STUB = f"""#!{sys.executable}
import json, os, sys
name = os.path.basename(sys.argv[0])
arguments = sys.argv[1:]
spec = json.load(open(os.environ["APEX_PARITY_SPEC"]))
with open(os.environ["APEX_PARITY_LOG"], "a") as log:
    log.write(json.dumps([name, *arguments]) + "\\n")
if name == "id":
    sys.stdout.write("0\\n")
elif name == "cat":
    marker = arguments == ["/etc/apex-builder"]
    sys.stdout.write("apex-isolated-builder-v1\\n" if marker else open(arguments[0]).read())
elif name == "podman":
    sys.stdout.write(spec["target_rpms"])
elif name == "rpm":
    sys.stdout.write(spec["installed_rpms"] if arguments[0] == "-q" else spec["environment_rpms"])
elif name == "curl":
    url = next(item for item in arguments if item.startswith("https://"))
    with open(arguments[arguments.index("-o") + 1], "w") as handle:
        handle.write(spec["bodies"][url[len(spec["base"]):]])
elif name == "timeout":
    rest = arguments[2:]
    os.execvp(rest[0], rest)
elif name == "runuser":
    if spec["report"] is not None:
        with open(os.path.join(arguments[-1], "results.json"), "w") as handle:
            json.dump(spec["report"], handle)
    sys.exit(spec["harness_exit"])
"""


@pytest.fixture
def workspaces() -> Iterator[tuple[Path, Path]]:
    if not os.access(VAR_TMP, os.W_OK) or shutil.which("jq") is None:
        pytest.skip("NOT TESTED: /var/tmp is not writable here or jq is absent")
    older = VAR_TMP / f"apex-fingerprint-{secrets.token_hex(16)}"
    newer = VAR_TMP / f"apex-fingerprint-{secrets.token_hex(16)}"
    older.mkdir(mode=0o700)
    newer.mkdir(mode=0o700)
    try:
        yield older, newer
    finally:
        shutil.rmtree(older, ignore_errors=True)
        shutil.rmtree(newer, ignore_errors=True)


def older_run(
    work: Path, spec: BuilderSpec, tmp_path: Path
) -> tuple[list[list[str]], subprocess.CompletedProcess[str]]:
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    for name in STUBBED:
        stub = stubs / name
        stub.write_text(STUB)
        stub.chmod(0o755)
    (work / "config").mkdir()
    (work / "config" / "fingerprint-tests.lock.json").write_text(
        json.dumps(lock_document(spec.bodies))
    )
    spec_file = tmp_path / "spec.json"
    spec_file.write_text(json.dumps(spec.as_document()))
    log = tmp_path / "older.log"
    environment = {
        **os.environ,
        "PATH": f"{stubs}:{os.environ.get('PATH', '/usr/bin')}",
        "APEX_PARITY_SPEC": str(spec_file),
        "APEX_PARITY_LOG": str(log),
        "LC_ALL": "C",
    }
    completed = subprocess.run(
        ["bash", str(OLDER_SCRIPT), IMAGE_ID],
        cwd=work, env=environment, capture_output=True, text=True, check=False,
    )
    calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
    return calls, completed


def newer_run(
    work: Path, spec: BuilderSpec, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[list[list[str]], dict[str, Any]]:
    def write(path: Path, payload: bytes) -> None:
        path.write_bytes(payload)

    process = Builder(spec, write)
    marker = tmp_path / "apex-builder"
    marker.write_text(f"{defaults.BUILDER_MARKER_TEXT}\n")
    monkeypatch.setattr(defaults, "BUILDER_MARKER", str(marker))
    monkeypatch.setattr(builder.os, "geteuid", lambda: 0)
    (work / "config").mkdir()
    (work / "config" / "fingerprint-tests.lock.json").write_text(
        json.dumps(lock_document(spec.bodies))
    )
    for name, body in spec.placed().items():
        target = work / "fingerprint-sources" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
    (work / "target-image.json").write_text(json.dumps(FROZEN))
    ports = agentports.AgentPorts(
        processes=process,
        files=real_files.LocalFiles(),
        clock=fake_clock.ManualClock(),
        containers=real_containers.PodmanEngine(process),
        digests=real_digesting.CachedDigests(),
        archives=real_archives.TarArchives(),
        identities=fake_ids.SequenceIdentities(),
        extents=fake_extents.FakeExtents(),
        blocks=fake_blockdevices.FakeBlockDevices(),
    )
    report = fingerprint_cleanup_unit.run(ports, arguments={"work": str(work)})
    return [[str(item) for item in call] for call in process.calls], dict(report)


def podman_normal(call: list[str]) -> list[str]:
    """The engine adapter orders the run options its own way; the set is what must agree."""
    if call[:2] != ["podman", "run"]:
        return call
    image = next(index for index, item in enumerate(call) if item.startswith("sha256:"))
    options = call[2:image]
    groups: list[str] = []
    index = 0
    while index < len(options):
        if options[index] in ("--network", "--entrypoint"):
            groups.append(f"{options[index]} {options[index + 1]}")
            index += 2
        else:
            groups.append(options[index])
            index += 1
    return ["podman", "run", *sorted(groups), *call[image:]]


def normalised_older(calls: list[list[str]]) -> list[list[str]]:
    return [
        podman_normal([RELATIVE.get(item, item) for item in call])
        for call in calls
        if call[0] not in HOST_SIDE
    ]


def normalised_newer(calls: list[list[str]], work: Path) -> list[list[str]]:
    return [
        podman_normal([item.replace(str(work), "WORK") for item in call])
        for call in calls
        if call[0] != "systemd-detect-virt"
    ]


@pytest.mark.parametrize(
    "spec,expected",
    [
        (BuilderSpec(), "PASS"),
        (
            BuilderSpec(
                report={"status": "FAIL", "tests_run": 8, "skipped": [], "failures": [["c", "t"]]},
                harness_exit=1,
            ),
            "FAIL",
        ),
    ],
)
def test_both_sides_run_the_same_programs_and_leave_the_same_evidence(
    spec: BuilderSpec,
    expected: str,
    workspaces: tuple[Path, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    older, newer = workspaces

    older_calls, completed = older_run(older, spec, tmp_path)
    newer_calls, report = newer_run(newer, spec, tmp_path, monkeypatch)

    assert normalised_newer(newer_calls, newer) == normalised_older(older_calls), completed.stderr
    assert (completed.returncode == 0) == (expected == "PASS")
    assert report["status"] == expected
    for name in EVIDENCE:
        assert (newer / "output" / "fingerprint" / name).read_bytes() == (
            older / "output" / "fingerprint" / name
        ).read_bytes(), name


def test_the_downloads_the_older_shell_made_are_the_pins_the_host_now_fetches(
    workspaces: tuple[Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    older, newer = workspaces
    spec = BuilderSpec()

    older_calls, _ = older_run(older, spec, tmp_path)
    _, report = newer_run(newer, spec, tmp_path, monkeypatch)

    fetched = [
        next(item for item in call if item.startswith("https://"))
        for call in older_calls
        if call[0] == "curl"
    ]
    assert sorted(fetched) == sorted(f"{BASE}{name}" for name in BODIES)
    assert report["sources"] == lock_document()["files"]
    timeouts = [call for call in older_calls if call[0] == "timeout"]
    assert timeouts[0][2] == f"{int(defaults.FINGERPRINT_TEST_DEADLINE.budget.seconds)}s"
