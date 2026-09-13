"""The fingerprint cleanup recipe, run end to end on fakes against a builder.

The builder proves itself, the tests are fetched on the host, the parent build is frozen as
the target, the work is laid out and the archive imported, the fault runs, and then the
chain refuses the fake bundle: a simulated run is never recorded.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest
from answeringguest import Answer, AnsweringGuest
from parentbuild import PARENT, documents
from test_desktop_theme_recipe import recorder

from apex.adapters.fakes import fake_downloading, fake_files, fake_guestshell
from apex.composition.stages import check_builder_stage
from apex.config import defaults
from apex.kernel import claims, refusals, safepaths, verdicts
from apex.ports import guestshell, portset
from apex.verification import verifykeys
from apex.verification.recipes import fingerprint_cleanup_recipe

REPOSITORY = Path(__file__).resolve().parents[2]


def answers(**changes: Answer | list[Answer]) -> dict[str, Answer | list[Answer]]:
    table: dict[str, Answer | list[Answer]] = {
        "build.import-payload": {"tag": "localhost/apex-payload:x"},
        "fault.fingerprint-cleanup": {"status": "PASS", "harness_returncode": 0},
    }
    table.update(changes)
    return table


@pytest.fixture
def root(tmp_path: Path) -> safepaths.RuntimeRoot:
    base = tmp_path / "runtime"
    base.mkdir(mode=0o700)
    (base / "builder_ed25519").write_bytes(b"")
    (base / "apex-agent.whl").write_bytes(b"not a wheel")
    return safepaths.RuntimeRoot.adopt(base)


def builder(root: safepaths.RuntimeRoot) -> guestshell.GuestTarget:
    return guestshell.GuestTarget(
        user=defaults.BUILDER_USER,
        port=defaults.BUILDER_SSH_PORT,
        key=safepaths.SafePath.regular_file(root.path / "builder_ed25519", within=root),
        known_hosts=root.child(defaults.KNOWN_HOSTS_NAME),
    )


def verify(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot, guest: AnsweringGuest
) -> tuple[object, fake_downloading.PinningFetcher]:
    assert isinstance(ports.files, fake_files.MemoryFiles)
    fetcher = fake_downloading.PinningFetcher()
    bundle = dataclasses.replace(ports, guest=guest, downloads=fetcher)
    documents(bundle.files, root)
    outcome = fingerprint_cleanup_recipe.verify(
        bundle,
        builder=builder(root),
        wheel=safepaths.SafePath.regular_file(root.path / "apex-agent.whl", within=root),
        parent=PARENT,
        witness=claims.EnvironmentKind.BUILD,
        recorder=recorder(root),
        root=root,
        repository=safepaths.SourceRoot.adopt(REPOSITORY),
    )
    return outcome, fetcher


def test_the_plan_guards_delivers_fetches_freezes_lays_out_imports_faults_then_records() -> None:
    assert [str(item) for item in fingerprint_cleanup_recipe.PLAN.order] == [
        "builder.guard",
        "run.identify",
        "agent.deliver",
        "fingerprint.acquire",
        "target.freeze",
        "fingerprint.work",
        "payload.import",
        "fault.fingerprint-cleanup",
        "attest.fingerprint.virtual-cleanup",
    ]


def test_the_fault_runs_over_the_work_the_host_laid_out_and_the_fake_bundle_is_refused(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    guest = AnsweringGuest(answers())

    outcome, fetcher = verify(ports, root, guest)

    assert outcome.refusal is refusals.RefusalReason.SIMULATED_ENVIRONMENT  # type: ignore[attr-defined]
    assert outcome.not_tested == (fingerprint_cleanup_recipe.CHECK,)  # type: ignore[attr-defined]
    assert guest.asked == ["build.import-payload", "fault.fingerprint-cleanup"]
    facts = outcome.facts  # type: ignore[attr-defined]
    work = facts[verifykeys.WORK]
    assert str(work).startswith("/var/tmp/apex-fingerprint-")
    assert [request["arguments"] for request in guest.requests] == [
        {"work": str(work), "parent": str(PARENT)}, {"work": str(work)},
    ]
    report = facts[verifykeys.fault_report(fingerprint_cleanup_recipe.CASE)]
    assert report.verdict is verdicts.PASSED
    assert facts[verifykeys.CANDIDATE] == facts[verifykeys.TARGET].digest
    remotes = [str(item.remote) for item in guest.sent]
    assert remotes[0].endswith(defaults.AGENT_WHEEL_NAME)
    assert f"{work}/config/fingerprint-tests.lock.json" in remotes
    assert f"{work}/target-image.json" in remotes
    assert len(fetcher.fetched) == len(facts[verifykeys.TEST_SOURCES].files) > 0
    assert all(guest.targets[0] == target for target in guest.targets)
    assert guest.targets[0].user == "builder"


def test_a_fault_that_fails_is_a_failed_report_still_refused_by_the_chain(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    failing: Answer = {"status": "FAIL"}
    guest = AnsweringGuest(answers(**{"fault.fingerprint-cleanup": failing}))

    outcome, _ = verify(ports, root, guest)

    facts = outcome.facts  # type: ignore[attr-defined]
    report = facts[verifykeys.fault_report(fingerprint_cleanup_recipe.CASE)]
    assert report.verdict is verdicts.FAILED
    assert outcome.refusal is refusals.RefusalReason.SIMULATED_ENVIRONMENT  # type: ignore[attr-defined]


def test_a_guest_that_is_not_the_builder_stops_the_run_before_anything_is_fetched(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    guest = AnsweringGuest(answers())
    guest.expect(check_builder_stage.CHECK.rendered(), fake_guestshell.GuestReply(exit_code=1))

    outcome, fetcher = verify(ports, root, guest)

    assert outcome.refusal is refusals.RefusalReason.BUILDER_NOT_ISOLATED  # type: ignore[attr-defined]
    assert guest.asked == [] and guest.sent == []
    assert fetcher.fetched == []
