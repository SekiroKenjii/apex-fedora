"""A rewrite happens only on the block device the snapshot described, or not at all.

The real adapter cannot be given a disposable block device on a development host or in
continuous integration, so its accepting and denying paths are NOT TESTED here and are
proven by the live fault in a guest. What both adapters prove the same way is the refusal:
a path that is not the device named by number is never opened for the write.
"""

from __future__ import annotations

import errno
from pathlib import Path

import pytest

from apex.adapters.fakes import fake_blockdevices
from apex.kernel import errors, refusals, safepaths
from apex.ports import blockdevices, files

NULL = safepaths.SafePath(Path("/dev/null"))
NULL_NUMBER = files.DeviceNumber(1, 3)
OTHER_NUMBER = files.DeviceNumber(1, 5)


def declared(blocks: blockdevices.BlockDevicePort) -> None:
    if isinstance(blocks, fake_blockdevices.FakeBlockDevices):
        blocks.declare(NULL, fake_blockdevices.FakeNode(number=NULL_NUMBER, content=bytes(512)))


def test_a_node_with_another_number_is_refused_before_any_read(
    blocks: blockdevices.BlockDevicePort,
) -> None:
    declared(blocks)

    with pytest.raises(errors.Refusal) as caught:
        blocks.rewrite(NULL, expected=OTHER_NUMBER, offset=0, length=512)

    assert caught.value.reason is refusals.RefusalReason.DEVICE_IDENTITY_MISMATCH


def test_a_character_device_is_not_a_block_device(
    blocks: blockdevices.BlockDevicePort,
) -> None:
    """The null device carries the number it is asked for, and is still refused."""
    if isinstance(blocks, fake_blockdevices.FakeBlockDevices):
        pytest.skip("NOT TESTED: the fake holds only block devices")

    with pytest.raises(errors.Refusal) as caught:
        blocks.rewrite(NULL, expected=NULL_NUMBER, offset=0, length=512)

    assert caught.value.reason is refusals.RefusalReason.DEVICE_IDENTITY_MISMATCH


def test_a_regular_file_is_refused(
    blocks: blockdevices.BlockDevicePort, root: safepaths.RuntimeRoot
) -> None:
    target = root.path / "disk.img"
    target.write_bytes(bytes(1024))

    with pytest.raises(errors.Refusal):
        blocks.rewrite(root.child("disk.img"), expected=NULL_NUMBER, offset=0, length=512)


def test_an_absent_node_is_a_port_failure_on_the_real_adapter(
    blocks: blockdevices.BlockDevicePort, root: safepaths.RuntimeRoot
) -> None:
    if isinstance(blocks, fake_blockdevices.FakeBlockDevices):
        pytest.skip("NOT TESTED: the fake has no absent nodes, only undeclared ones")

    with pytest.raises(errors.PortFailure):
        blocks.rewrite(root.child("absent"), expected=NULL_NUMBER, offset=0, length=512)


def test_a_denied_write_leaves_the_bytes_unchanged(
    blocks: blockdevices.BlockDevicePort,
) -> None:
    if not isinstance(blocks, fake_blockdevices.FakeBlockDevices):
        pytest.skip("NOT TESTED: no disposable block device on this host")
    node = safepaths.SafePath(Path("/dev/vdb"))
    blocks.declare(node, fake_blockdevices.FakeNode(files.DeviceNumber(253, 16), b"x" * 512))

    outcome = blocks.rewrite(node, expected=files.DeviceNumber(253, 16), offset=0, length=512)

    assert outcome.denied and outcome.unchanged
    assert outcome.written is None and outcome.error_number == errno.EROFS


def test_an_accepted_write_reports_the_bytes_written(
    blocks: blockdevices.BlockDevicePort,
) -> None:
    if not isinstance(blocks, fake_blockdevices.FakeBlockDevices):
        pytest.skip("NOT TESTED: no disposable block device on this host")
    node = safepaths.SafePath(Path("/dev/vdb"))
    blocks.declare(
        node, fake_blockdevices.FakeNode(files.DeviceNumber(253, 16), b"x" * 512, denial=None)
    )

    outcome = blocks.rewrite(node, expected=files.DeviceNumber(253, 16), offset=0, length=512)

    assert not outcome.denied and outcome.unchanged and outcome.written == 512


def test_a_short_device_is_a_port_failure(blocks: blockdevices.BlockDevicePort) -> None:
    if not isinstance(blocks, fake_blockdevices.FakeBlockDevices):
        pytest.skip("NOT TESTED: no disposable block device on this host")
    node = safepaths.SafePath(Path("/dev/vdb"))
    blocks.declare(node, fake_blockdevices.FakeNode(files.DeviceNumber(253, 16), b"x" * 100))

    with pytest.raises(errors.PortFailure):
        blocks.rewrite(node, expected=files.DeviceNumber(253, 16), offset=0, length=512)
