import pytest
from apexlib.hda import decode_coefficient


def test_overlapping_verb_bits_change_coefficient():
    result = decode_coefficient(0x20, 0x477, 0x4a4b)
    assert result['canonical_verb'] == '0x400'
    assert result['effective_parameter'] == '0x7f4b'
    assert result['hwdep_word'] == '0x20047f4b'
    assert result['parameter_changed_by_overlap']
    assert not result['device_access']


def test_short_parameter_also_inherits_verb_bits():
    assert decode_coefficient(0x20, 0x477, 0x74)['effective_parameter'] == '0x7774'


def test_canonical_verb_preserves_parameter():
    result = decode_coefficient(0x20, 0x400, 0x4a4b)
    assert result['effective_parameter'] == '0x4a4b'
    assert not result['parameter_changed_by_overlap']


def test_index_selection():
    assert decode_coefficient(0x20, 0x500, 0x1b)['effective_parameter'] == '0x001b'


def test_reported_four_command_sequence_is_not_asus_coef_1b():
    operands = ((0x500, 0x1b), (0x477, 0x4a4b), (0x500, 0xf), (0x477, 0x74))
    decoded = [decode_coefficient(0x20, verb, parameter) for verb, parameter in operands]
    assert [(row['canonical_verb'], row['effective_parameter']) for row in decoded] == [
        ('0x500', '0x001b'), ('0x400', '0x7f4b'), ('0x500', '0x000f'), ('0x400', '0x7774')]
    assert int(decoded[1]['effective_parameter'], 16) ^ 0x4e4b == 0x3100
    assert all(row['device_access'] is False for row in decoded)


@pytest.mark.parametrize('args', [(0x100, 0x500, 0), (0x20, 0x400, 0x10000), (0x20, 0x707, 0x40)])
def test_invalid_or_unrelated_verb_is_rejected(args):
    with pytest.raises(ValueError):
        decode_coefficient(*args)
