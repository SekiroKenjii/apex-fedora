import pytest
from apexlib.render import swatches


def test_requires_adjacent_wide_color_bars(tmp_path):
    path = tmp_path / 'frame.ppm'
    row = b'\xe6\x26\x26' * 100 + b'\x26\xbf\x40' * 100 + b'\x26\x4c\xe6' * 100
    path.write_bytes(b'P6\n300 100\n255\n' + row * 100)
    assert swatches(path)['matched_rows_at_stride_four'] == 25


def test_a_blank_or_small_icon_frame_is_not_a_render_pass(tmp_path):
    path = tmp_path / 'frame.ppm'
    path.write_bytes(b'P6\n300 100\n255\n' + b'\x00\x00\x00' * 300 * 100)
    with pytest.raises(AssertionError, match='visibly rendered'):
        swatches(path)
