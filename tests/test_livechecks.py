import pytest
from apexlib.livechecks import decode_object, source_for, PROBES


@pytest.mark.parametrize('case', PROBES)
def test_composed_probe_compiles_without_executing_host_mutations(case):
    source = source_for(case)
    compile(source, '<test-source>', 'exec')
    assert len(source.encode()) <= 65536
    if case == 'lock-fault':
        assert 'EXPECTED_GUARD_SHA256=' in source
    if case in {'lock-fault', 'usb-write-denial'}:
        assert "ModuleType('apex_live_write')" in source


def test_terminal_escape_prefix_does_not_confuse_object_decoder():
    assert decode_object(b'\x1b[?2004l\r\n{"status":"PASS"}\r\nAPEXDONE:x:0\n') == {'status': 'PASS'}


def test_missing_json_is_not_success():
    with pytest.raises(ValueError):
        decode_object(b'No structured result')
