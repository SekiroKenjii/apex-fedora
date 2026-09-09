import importlib.util
from pathlib import Path

import pytest

from apexlib.common import Blocked


def module():
    spec = importlib.util.spec_from_file_location('compact', Path(__file__).resolve().parents[1] / 'tools/compact-builder.py')
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


@pytest.mark.parametrize('change', [{'snapshots': [{}]}, {'dirty-flag': True},
                                  {'format-specific': {'data': {'bitmaps': [{}]}}},
                                  {'format-specific': {'data': {'corrupt': True}}}])
def test_compaction_refuses_metadata_that_would_be_lost(change):
    with pytest.raises(Blocked):
        module().validate_info([{'format': 'qcow2'} | change])


def test_compaction_accepts_a_clean_chain():
    module().validate_info([{'format': 'qcow2'}, {'format': 'qcow2'}])


def test_compaction_refuses_a_non_qcow2_source():
    with pytest.raises(Blocked):
        module().validate_info([{'format': 'raw'}])
