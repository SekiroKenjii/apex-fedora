"""The decisions the older fixture scripts make, made the same way by the host-side modules.

Each older script is loaded from `guest/` as it ships. Only its pure functions are called,
which is exactly the set that moved.
"""

from __future__ import annotations

import base64
import importlib.util
import json
import types
from pathlib import Path

import pytest

from apex.kernel import errors, hashing, identifiers, safepaths
from apex.provisioning.fixtures import (
    dedupe_fixture,
    initramfs_fixture,
    recovery_fixture,
    update_fixture,
    ventoy_fixture,
)

GUEST = Path(__file__).resolve().parents[2] / "guest"
RUN = identifiers.RunId("b" * 32)
BAD = identifiers.ImageId("c" * 64)
BOOTLINK_A = "/ostree/boot.1/fedora/" + "a" * 64 + "/0"
BOOTLINK_B = "/ostree/boot.1/fedora/" + "b" * 64 + "/0"


def older(name: str) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), GUEST / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def entry(*, version: str, bootlink: str, initrd: str = "/boot/ostree/x-1/initramfs.img") -> str:
    return (
        f"title Fedora\nversion {version}\n"
        f"options root=UUID=1 ostree={bootlink}\n"
        f"linux /boot/ostree/x-1/vmlinuz\ninitrd {initrd}\n"
    )


def test_a_boot_entry_parses_to_the_same_fields() -> None:
    text = entry(version="2", bootlink=BOOTLINK_B)

    parsed = initramfs_fixture.parse_entry(text)
    expected = older("initramfs-fixture").parse_entry(text)

    assert {
        "title": parsed.title, "version": parsed.version, "options": parsed.options,
        "linux": parsed.linux, "initrd": parsed.initrd, "bootlink": parsed.bootlink,
    } == expected


@pytest.mark.parametrize(
    "text",
    [
        "title Fedora\n",
        entry(version="1", bootlink=BOOTLINK_A) + "extra field\n",
        entry(version="1", bootlink=BOOTLINK_A, initrd="/boot/ostree/../etc/x"),
        entry(version="1", bootlink=BOOTLINK_A, initrd="/boot/ostree/x y"),
        entry(version="1", bootlink="/ostree/boot.9/x/0"),
        "title a\ntitle b\nversion 1\noptions x\nlinux y\ninitrd z\n",
    ],
)
def test_both_refuse_the_same_malformed_entries(text: str) -> None:
    with pytest.raises(ValueError, match=r"."):
        older("initramfs-fixture").parse_entry(text)
    with pytest.raises(errors.Refusal):
        initramfs_fixture.parse_entry(text)


def test_a_fault_path_is_admitted_only_when_asked_for() -> None:
    fault = f"/apex-initramfs-fault/{RUN}/bad.img"
    text = entry(version="2", bootlink=BOOTLINK_B, initrd=fault)

    assert initramfs_fixture.parse_entry(text, allow_fault=True).initrd == fault
    assert older("initramfs-fixture").parse_entry(text, allow_fault=True)["initrd"] == fault
    with pytest.raises(errors.Refusal):
        initramfs_fixture.parse_entry(text)


def test_the_modified_entry_is_byte_identical() -> None:
    text = entry(version="2", bootlink=BOOTLINK_B)
    fault = f"/apex-initramfs-fault/{RUN}/bad.img"

    assert initramfs_fixture.modified_entry(text, fault) == older(
        "initramfs-fixture"
    ).modified_entry(text, fault)


def test_the_rescue_verdict_agrees_both_ways() -> None:
    legacy = older("initramfs-fixture")
    for a_initrd, safe in (("/boot/ostree/x-1/initramfs.img", True),
                           (f"/apex-initramfs-fault/{RUN}/bad.img", False)):
        a_text = entry(version="1", bootlink=BOOTLINK_A, initrd=a_initrd)
        b_text = entry(version="2", bootlink=BOOTLINK_B)
        entries = {
            "a": initramfs_fixture.parse_entry(a_text, allow_fault=True),
            "b": initramfs_fixture.parse_entry(b_text),
        }
        expected = legacy.rescue_binding({
            "a": {"fields": legacy.parse_entry(a_text, allow_fault=True)},
            "b": {"fields": legacy.parse_entry(b_text)},
        })

        verdict = initramfs_fixture.rescue_binding(entries)

        assert verdict.safe_to_reboot_a is safe is expected["safe_to_reboot_a"]
        assert verdict.reason == expected["reason"]


def test_the_corrupted_head_matches_the_older_overwrite() -> None:
    head = bytes(range(64))

    assert initramfs_fixture.corrupted_head(head) == (
        b"APEX_BAD_INITRD\n" + head[len(b"APEX_BAD_INITRD\n"):]
    )


def test_the_grub_repair_is_byte_identical_and_refuses_the_same_preimages() -> None:
    legacy = older("recovery-fixture")
    broken = b"set x=1\nsave_env boot_success### END 08_greenboot.cfg ###\n"
    fragment = b"# fragment\nsave_env boot_success\n"

    assert recovery_fixture.repaired_config(broken, fragment) == legacy.repaired_config(
        broken, fragment
    )
    for current, fragment_text in (
        (broken, b"no tail"),
        (b"already\nsave_env boot_success\n### END 08_greenboot.cfg ###\n", fragment),
        (broken * 2, fragment),
    ):
        with pytest.raises(ValueError, match=r"."):
            legacy.repaired_config(current, fragment_text)
        with pytest.raises(errors.Refusal):
            recovery_fixture.repaired_config(current, fragment_text)


def test_the_observer_program_is_byte_identical() -> None:
    destination = f"/var/lib/apex-recovery-test/{RUN}"

    assert recovery_fixture.observer_program(
        BAD, safepaths.RemotePath(destination)
    ) == older("recovery-fixture").fault_payload(str(BAD), Path(destination))


def test_the_signing_policy_is_the_same_document() -> None:
    key = b"public key bytes"

    assert json.loads(json.dumps(update_fixture.policy(key, RUN))) == older(
        "update-fixture"
    ).policy(key, str(RUN))
    assert base64.b64decode(
        update_fixture.policy(key, RUN)["transports"]["dir"][  # type: ignore[index]
            f"/var/lib/apex-update-fixture/{RUN}/a"
        ][0]["keyData"]
    ) == key


def test_the_container_recipes_match_the_older_assembly() -> None:
    parent = "localhost/apex-payload:" + "d" * 64
    first = update_fixture.image_tag(RUN, "a")
    older_a = (
        f"FROM {parent}\n"
        "COPY policy.json /etc/containers/policy.json\n"
        "COPY greenboot.conf /usr/share/apex/greenboot.conf\n"
        "COPY greenboot.conf /etc/greenboot/greenboot.conf\n"
        "COPY fix-grub-fragment.py /tmp/fix-grub-fragment.py\n"
        "RUN python3 /tmp/fix-grub-fragment.py "
        "/usr/lib/bootupd/grub2-static/configs.d/08_greenboot.cfg "
        "> /usr/share/apex/greenboot-fragment.json && rm /tmp/fix-grub-fragment.py\n"
        "COPY marker.json /usr/share/apex/recovery-fixture.json\n"
    )

    assert update_fixture.containerfile("a", parent=parent, first=first) == older_a
    assert update_fixture.containerfile("b", parent=parent, first=first) == (
        f"FROM {first}\nCOPY marker.json /usr/share/apex/recovery-fixture.json\n"
    )


def test_the_ventoy_request_is_accepted_and_refused_alike(tmp_path: Path) -> None:
    legacy = older("ventoy-fixture")
    files = {}
    for name in ("ventoy.tar.gz", "Apex-Live.iso", "Ubuntu.iso"):
        (tmp_path / name).write_bytes(name.encode())
        files[name] = hashing.digest_bytes(name.encode()).hex
    request = {"files": files, "ventoy_version": "1.0.99"}

    legacy.verify_inputs(tmp_path, request)
    parsed = ventoy_fixture.parse_request(request)

    assert parsed.version == "1.0.99"
    assert {name: digest.hex for name, digest in parsed.files.items()} == files
    for damaged in (
        {"files": {**files, "Extra.iso": files["Ubuntu.iso"]}, "ventoy_version": "1.0.99"},
        {"files": {**files, "Ubuntu.iso": "nothex"}, "ventoy_version": "1.0.99"},
        {"files": files, "ventoy_version": "1.0"},
    ):
        with pytest.raises(RuntimeError):
            legacy.verify_inputs(tmp_path, damaged)
        with pytest.raises(errors.Refusal):
            ventoy_fixture.parse_request(damaged)


def test_the_dedupe_ioctl_layout_is_unchanged() -> None:
    legacy = older("dedupe-update-blobs")

    assert dedupe_fixture.FIDEDUPERANGE == legacy.FIDEDUPERANGE
    assert dedupe_fixture.HEADER.format == legacy.HEADER.format
    assert dedupe_fixture.INFO.format == legacy.INFO.format
    assert dedupe_fixture.CHUNK.bytes == legacy.CHUNK
