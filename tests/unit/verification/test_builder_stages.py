"""The builder recipe's stages: the guard, the fetch, the target, the work and the import."""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

import pytest
from answeringguest import AnsweringGuest
from parentbuild import PARENT, documents

from apex.adapters.fakes import fake_downloading, fake_guestshell
from apex.composition import agentrun
from apex.composition import keys as composition_keys
from apex.composition.stages import check_builder_stage
from apex.config import defaults, fingerprintpins
from apex.kernel import commands, identifiers, refusals, safepaths, verdicts
from apex.pipeline import facts, stages
from apex.ports import guestshell, portset
from apex.trust import testsources
from apex.verification import faults, verifykeys
from apex.verification.stages import (
    acquire_tests_stage,
    builder_guard_stage,
    fault_stage,
    fingerprint_work_stage,
    import_payload_stage,
    target_image_stage,
)

REPOSITORY = Path(__file__).resolve().parents[3]
SEED = identifiers.StageId("seed")
RUN = identifiers.RunId("b" * 32)
WORK = safepaths.RemotePath(f"/var/tmp/apex-fingerprint-{RUN}")
SOURCES = (
    testsources.AcquiredFile("fprintd.py", identifiers.Digest("1" * 64), fetched=True),
    testsources.AcquiredFile("dbusmock/polkitd.py", identifiers.Digest("2" * 64), fetched=False),
)


class RefusingMkdir(AnsweringGuest):
    """A guest whose directories cannot be made."""

    def run(self, target: guestshell.GuestTarget, run: guestshell.GuestRun) -> Any:
        if run.script.rendered().startswith("mkdir"):
            self.runs.append(run)
            return commands.CompletedRun(
                exit_code=1, stdout=b"", stderr=b"mkdir: refused", truncated=False
            )
        return super().run(target, run)


@pytest.fixture
def root(tmp_path: Path) -> safepaths.RuntimeRoot:
    base = tmp_path / "runtime"
    base.mkdir(mode=0o700)
    (base / "builder_ed25519").write_bytes(b"")
    return safepaths.RuntimeRoot.adopt(base)


def builder(root: safepaths.RuntimeRoot) -> guestshell.GuestTarget:
    return guestshell.GuestTarget(
        user=defaults.BUILDER_USER,
        port=defaults.BUILDER_SSH_PORT,
        key=safepaths.SafePath.regular_file(root.path / "builder_ed25519", within=root),
        known_hosts=root.child(defaults.KNOWN_HOSTS_NAME),
    )


def context(
    ports: portset.HostPorts,
    root: safepaths.RuntimeRoot,
    guest: fake_guestshell.ScriptedGuest,
    **held: object,
) -> stages.RunContext[portset.HostPorts]:
    bundle = dataclasses.replace(ports, guest=guest, downloads=fake_downloading.PinningFetcher())
    given = facts.FactMap()
    seeded: dict[facts.FactKey[Any], object] = {
        verifykeys.BUILDER: builder(root),
        verifykeys.GUEST: builder(root),
        verifykeys.AGENT: agentrun.AgentInstall(
            directory=safepaths.RemotePath("/var/tmp/apex-run/agent"),
            digest=identifiers.Digest("a" * 64),
        ),
        verifykeys.PARENT: PARENT,
        verifykeys.WORK: WORK,
        composition_keys.RUNTIME_ROOT: root,
        composition_keys.RUN_ID: RUN,
        composition_keys.REPOSITORY: safepaths.SourceRoot.adopt(REPOSITORY),
    }
    for name, value in held.items():
        seeded[getattr(verifykeys, name.upper())] = value
    for key, value in seeded.items():
        given = given.with_fact(key, value, produced_by=SEED)
    return stages.RunContext(facts=given, ports=bundle)


def test_the_guard_admits_the_isolated_builder_as_the_guest(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    guest = AnsweringGuest({})
    run = context(ports, root, guest)

    result = builder_guard_stage.apply(run)

    assert isinstance(result, stages.Advance)
    assert result.facts[verifykeys.GUEST] == builder(root)
    assert [item.script.rendered() for item in guest.runs] == [check_builder_stage.CHECK.rendered()]


def test_a_guest_that_is_not_the_builder_is_refused_by_the_guard(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    guest = AnsweringGuest({})
    guest.expect(check_builder_stage.CHECK.rendered(), fake_guestshell.GuestReply(exit_code=1))

    result = builder_guard_stage.apply(context(ports, root, guest))

    assert isinstance(result, stages.Refuse)
    assert result.reason is refusals.RefusalReason.BUILDER_NOT_ISOLATED


def test_the_pinned_tests_are_fetched_on_the_host_against_the_reviewed_lock(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    run = context(ports, root, AnsweringGuest({}))

    result = acquire_tests_stage.apply(run)

    assert isinstance(result, stages.Advance)
    acquired = result.facts[verifykeys.TEST_SOURCES]
    reviewed = fingerprintpins.load(safepaths.SourceRoot.adopt(REPOSITORY))
    assert {item.name for item in acquired.files} == set(reviewed.files.names)
    assert all(item.fetched for item in acquired.files)
    assert run.ports.files.exists(testsources.lock_copy(root))
    fetcher = run.ports.downloads
    assert isinstance(fetcher, fake_downloading.PinningFetcher)
    assert len(fetcher.fetched) == len(reviewed.files.files)


def test_the_target_is_the_parents_frozen_image_and_its_digest_the_candidate(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    run = context(ports, root, AnsweringGuest({}))
    digest = documents(run.ports.files, root)

    result = target_image_stage.apply(run)

    assert isinstance(result, stages.Advance)
    assert result.facts[verifykeys.TARGET].digest == digest
    assert result.facts[verifykeys.CANDIDATE] == digest
    target = root.child(f"exports/{RUN}/target-image.json")
    assert run.ports.files.exists(target)


def test_a_parent_that_did_not_complete_refuses_the_target(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    run = context(ports, root, AnsweringGuest({}))
    documents(run.ports.files, root, status="FAIL")

    result = target_image_stage.apply(run)

    assert isinstance(result, stages.Refuse)
    assert result.reason is refusals.RefusalReason.BUILD_PARENT_NOT_COMPLETE


def acquired(root: safepaths.RuntimeRoot) -> testsources.Acquired:
    return testsources.Acquired(
        directory=root.child("fingerprint-tests"), files=SOURCES,
        lock_record=identifiers.Digest("3" * 64),
    )


def test_the_work_directory_is_laid_out_file_by_file_under_its_run(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    guest = AnsweringGuest({})
    run = context(ports, root, guest, test_sources=acquired(root), target=None)

    result = fingerprint_work_stage.apply(run)

    assert isinstance(result, stages.Advance)
    assert result.facts[verifykeys.WORK] == WORK
    made = guest.runs[0].script.rendered()
    assert made.startswith(f"mkdir -p -m 700 {WORK}")
    for name in ("fingerprint-sources", "fingerprint-sources/dbusmock", "config"):
        assert f"{WORK}/{name}" in made
    assert [(str(item.local), str(item.remote)) for item in guest.sent] == [
        (f"{root.path}/fingerprint-tests/fingerprint-sources/fprintd.py",
         f"{WORK}/fingerprint-sources/fprintd.py"),
        (f"{root.path}/fingerprint-tests/fingerprint-sources/dbusmock/polkitd.py",
         f"{WORK}/fingerprint-sources/dbusmock/polkitd.py"),
        (f"{root.path}/fingerprint-tests/config/fingerprint-tests.lock.json",
         f"{WORK}/config/fingerprint-tests.lock.json"),
        (f"{root.path}/exports/{RUN}/target-image.json", f"{WORK}/target-image.json"),
    ]


def test_a_guest_that_cannot_make_the_work_directory_fails_before_any_file_is_sent(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    guest = RefusingMkdir({})
    run = context(ports, root, guest, test_sources=acquired(root), target=None)

    result = fingerprint_work_stage.apply(run)

    assert isinstance(result, stages.Fail)
    assert guest.sent == []


def test_the_import_asks_the_builder_for_the_parents_archive_under_the_work(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    guest = AnsweringGuest({"build.import-payload": {"tag": "localhost/apex-payload:x"}})
    run = context(ports, root, guest)

    result = import_payload_stage.apply(run)

    assert isinstance(result, stages.Advance)
    assert result.facts[verifykeys.IMPORTED] == {"tag": "localhost/apex-payload:x"}
    assert guest.requests[-1]["arguments"] == {"work": str(WORK), "parent": str(PARENT)}
    assert "sudo" in guest.runs[-1].script.rendered()


def test_a_builder_that_refuses_the_import_refuses_the_stage(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    result = import_payload_stage.apply(context(ports, root, AnsweringGuest({})))

    assert isinstance(result, stages.Refuse)
    assert result.reason is refusals.RefusalReason.AGENT_REFUSED


def test_a_fault_case_is_asked_with_the_arguments_the_run_holds(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    case = faults.lookup(identifiers.ProbeId("fault.fingerprint-cleanup"))
    guest = AnsweringGuest({"fault.fingerprint-cleanup": {"status": "PASS"}})
    stage = fault_stage.for_case(
        case, arguments=lambda held: {"work": str(held.facts[verifykeys.WORK])},
        after=(verifykeys.WORK,),
    )

    result = stage.apply(context(ports, root, guest))

    assert isinstance(result, stages.Advance)
    report = result.facts[verifykeys.fault_report(case)]
    assert report.verdict is verdicts.PASSED
    assert report.case.arguments == {"work": str(WORK)}
    assert guest.requests[-1]["arguments"] == {"work": str(WORK)}
    assert verifykeys.WORK in stage.reads
