"""What each fixture's host side accepts, derives and refuses."""

from __future__ import annotations

import pytest

from apex.kernel import errors, refusals
from apex.provisioning.fixtures import (
    dedupe_fixture,
    initramfs_fixture,
    installer_fixture,
    recovery_fixture,
    update_fixture,
    ventoy_fixture,
)

HEX_64 = "e" * 64
RUN = "f" * 32


def test_the_installer_layout_carves_three_partitions_in_declared_order() -> None:
    text = installer_fixture.layout()

    assert text.startswith("label: gpt\n")
    assert text.splitlines()[1:] == [
        'size=512M,type=U,name="fixture-efi"',
        'size=1024M,type=EBD0A0A2-B9E5-4433-87C0-68B6B72699C7,name="fixture-windows"',
        'size=2048M,type=L,name="fixture-linux"',
    ]


def installer_report() -> dict[str, object]:
    return {
        "purpose": "installer disk preservation tests",
        "bootable_existing_systems": False,
        "partitions": [
            {"partition": index, "filesystem": fs, "sentinel": name, "sentinel_sha256": HEX_64}
            for index, fs, name in (
                (1, "vfat", "EFI/BOOT/apex-sentinel.txt"),
                (2, "ntfs-3g", "apex-sentinel.txt"),
                (3, "ext4", "apex-sentinel.txt"),
            )
        ],
        "sha256": {"other.qcow2": HEX_64, "target.qcow2": HEX_64},
    }


def test_an_installer_report_parses() -> None:
    report = installer_fixture.parse_report(installer_report())

    assert [item.partition for item in report.sentinels] == [1, 2, 3]
    assert set(report.images) == {"other.qcow2", "target.qcow2"}


@pytest.mark.parametrize(
    "change",
    [
        {"bootable_existing_systems": True},
        {"partitions": []},
        {"sha256": {"other.qcow2": HEX_64}},
        {"partitions": [{"partition": 1}]},
    ],
)
def test_a_damaged_installer_report_is_refused(change: dict[str, object]) -> None:
    with pytest.raises(errors.Refusal) as raised:
        installer_fixture.parse_report({**installer_report(), **change})

    assert raised.value.reason is refusals.RefusalReason.FIXTURE_REPORT_MALFORMED


def test_a_ventoy_report_parses_and_a_touched_medium_is_refused() -> None:
    request = {
        "files": dict.fromkeys(ventoy_fixture.INPUTS, HEX_64),
        "ventoy_version": "1.1.05",
    }
    document = {
        "status": "PASS", "request": request, "image_sha256": HEX_64,
        "physical_media_accessed": False,
    }

    assert ventoy_fixture.parse_report(document).request.version == "1.1.05"
    with pytest.raises(errors.Refusal):
        ventoy_fixture.parse_report({**document, "physical_media_accessed": True})
    with pytest.raises(errors.Refusal):
        ventoy_fixture.parse_report({**document, "status": "BLOCKED"})


def update_report() -> dict[str, object]:
    image = {"digest": f"sha256:{HEX_64}", "config": f"sha256:{HEX_64}", "identity": "x"}
    return {
        "status": "PASS", "id": RUN, "images": {"a": image, "b": image},
        "files": {"a/manifest.json": HEX_64}, "public_key_sha256": HEX_64,
        "archive_sha256": HEX_64,
    }


def test_an_update_report_parses_and_missing_images_are_refused() -> None:
    report = update_fixture.parse_report(update_report())

    assert set(report.images) == {"a", "b"}
    assert str(report.run) == RUN
    with pytest.raises(errors.Refusal) as raised:
        update_fixture.parse_report({**update_report(), "images": {"a": {}}})
    assert raised.value.reason is refusals.RefusalReason.FIXTURE_REPORT_MALFORMED


def test_the_retry_variant_changes_one_line_and_refuses_anything_else() -> None:
    before = b"# retries\nGREENBOOT_MAX_BOOT_ATTEMPTS=2\n"

    assert recovery_fixture.retry_config(before) == b"# retries\nGREENBOOT_MAX_BOOT_ATTEMPTS=1\n"
    with pytest.raises(errors.Refusal) as raised:
        recovery_fixture.retry_config(b"GREENBOOT_MAX_BOOT_ATTEMPTS=3\n")
    assert raised.value.reason is refusals.RefusalReason.FIXTURE_STATE_UNEXPECTED


def test_the_unit_overrides_name_the_observer_program() -> None:
    from apex.kernel import safepaths  # noqa: PLC0415

    overrides = recovery_fixture.unit_overrides(safepaths.RemotePath("/var/lib/x/observe.py"))

    assert set(overrides) == {"gdm.service", "greenboot-healthcheck.service"}
    assert "Restart=no" in overrides["gdm.service"]
    assert "/var/lib/x/observe.py health-after" in overrides["greenboot-healthcheck.service"]


def test_a_shared_boot_identity_is_not_isolated() -> None:
    a = initramfs_fixture.parse_entry(
        "title a\nversion 1\noptions ostree=/ostree/boot.1/f/" + "a" * 64 + "/0\n"
        "linux /boot/ostree/x/vmlinuz\ninitrd /boot/ostree/x/initramfs.img\n"
    )
    b = initramfs_fixture.parse_entry(
        "title b\nversion 2\noptions ostree=/ostree/boot.1/f/" + "a" * 64 + "/1\n"
        "linux /boot/ostree/y/vmlinuz\ninitrd /boot/ostree/y/initramfs.img\n"
    )

    with pytest.raises(errors.Refusal) as raised:
        initramfs_fixture.require_isolated(a, b, a_initrd=a.initrd, b_initrd=b.initrd)

    assert raised.value.reason is refusals.RefusalReason.FIXTURE_PATH_NOT_ISOLATED


def test_a_plan_digest_is_stable_across_key_order() -> None:
    first = initramfs_fixture.plan_digest({"b": 1, "a": [1, 2]})
    second = initramfs_fixture.plan_digest({"a": [1, 2], "b": 1})

    assert first == second


def test_dedupe_spans_cover_the_aligned_prefix_only() -> None:
    size = 2 * dedupe_fixture.CHUNK.bytes + 4096 + 100

    spans = dedupe_fixture.spans(size)

    assert [item.length for item in spans] == [
        dedupe_fixture.CHUNK.bytes, dedupe_fixture.CHUNK.bytes, 4096
    ]
    assert dedupe_fixture.shareable_length(size) == size - 100


def test_a_misaligned_dedupe_range_is_refused() -> None:
    with pytest.raises(errors.Refusal):
        dedupe_fixture.DedupeRange(offset=1, length=4096)


def test_a_dedupe_buffer_reads_back_its_outcome() -> None:
    buffer = dedupe_fixture.request_buffer(dedupe_fixture.DedupeRange(0, 4096), 7)

    outcome = dedupe_fixture.outcome_of(buffer)

    assert outcome.bytes_deduped == 0
    assert outcome.complete
    assert len(buffer) == dedupe_fixture.HEADER.size + dedupe_fixture.INFO.size


def test_the_update_policy_rejects_by_default_and_names_four_scopes() -> None:
    from apex.kernel import identifiers  # noqa: PLC0415

    document = update_fixture.policy(b"key", identifiers.RunId(RUN))

    assert document["default"] == [{"type": "reject"}]
    assert len(document["transports"]["dir"]) == 4  # type: ignore[index, arg-type]
