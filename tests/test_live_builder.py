import hashlib
import importlib.util

import pytest
from apexlib.common import ROOT

spec = importlib.util.spec_from_file_location('live_builder', ROOT / 'guest/prepare-live-builder.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


def test_preserve_ownership_and_export_filesystem_metadata(monkeypatch):
    source = b'#!/bin/bash\nmksquashfs /rootfs /work/iso-root/LiveOS/squashfs.img -all-root -noappend -comp zstd\n'
    monkeypatch.setattr(builder, 'UPSTREAM_SHA256', hashlib.sha256(source).hexdigest())
    result = builder.adapt(source)
    assert b'-all-root' not in result
    assert b'-noappend -comp zstd' in result
    assert b'unsquashfs -lln' in result


def test_refuse_unreviewed_or_already_modified_builder():
    with pytest.raises(ValueError, match='pinned Titanoboa'):
        builder.adapt(b'arbitrary replacement')
