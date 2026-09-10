import importlib.util
from pathlib import Path

import pytest


def module():
    spec = importlib.util.spec_from_file_location('dedupe', Path(__file__).resolve().parents[1] / 'guest/dedupe-update-blobs.py')
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def test_dedupe_encodes_the_reviewed_linux_abi(monkeypatch):
    tool = module()
    def ioctl(fd, operation, buffer, mutate):
        assert (fd, operation, mutate) == (3, 0xC0189436, True)
        assert len(buffer) == 56
        assert tool.HEADER.unpack_from(buffer) == (4096, 8192, 1, 0, 0)
        assert tool.INFO.unpack_from(buffer, 24) == (4, 4096, 0, 0, 0)
        tool.INFO.pack_into(buffer, 24, 4, 4096, 8192, 0, 0)
    monkeypatch.setattr(tool.fcntl, 'ioctl', ioctl)
    assert tool.request(3, 4, 4096, 8192) == 8192


@pytest.mark.parametrize('status,count', [(1, 0), (-22, 0), (0, 0), (0, 2048)])
def test_dedupe_rejects_difference_errors_and_partial_success(monkeypatch, status, count):
    tool = module()
    def ioctl(fd, operation, buffer, mutate):
        tool.INFO.pack_into(buffer, 24, 4, 0, count, status, 0)
    monkeypatch.setattr(tool.fcntl, 'ioctl', ioctl)
    with pytest.raises(ValueError):
        tool.request(3, 4, 0, 4096)


@pytest.mark.parametrize('offset,length', [(-4096, 4096), (1, 4096), (0, 0), (0, 4095)])
def test_dedupe_requires_block_aligned_requests(offset, length):
    with pytest.raises(ValueError):
        module().request(3, 4, offset, length)


def test_different_files_are_rejected_before_any_ioctl(tmp_path, monkeypatch):
    tool = module()
    source, target = tmp_path / 'source', tmp_path / 'target'
    source.write_bytes(b'A' * 4096)
    target.write_bytes(b'B' * 4096)
    monkeypatch.setattr(tool.fcntl, 'ioctl', lambda *args: pytest.fail('Unexpected ioctl'))
    with pytest.raises(ValueError, match='contents differ'):
        tool.share(source, target)
    assert source.read_bytes() == b'A' * 4096
    assert target.read_bytes() == b'B' * 4096
