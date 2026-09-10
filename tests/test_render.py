import pytest
from apexlib.render import swatches, surface_change


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


@pytest.mark.parametrize('changed_rows,passes', [(0, False), (40, False), (41, False), (80, True)])
def test_shell_change_rejects_clock_and_small_changes(tmp_path, changed_rows, passes):
    before, after = tmp_path / 'before.ppm', tmp_path / 'after.ppm'
    header = b'P6\n300 100\n255\n'
    before.write_bytes(header + b'\x00\x00\x00' * 300 * 100)
    after.write_bytes(header + b'\x40\x40\x40' * 300 * changed_rows + b'\x00\x00\x00' * 300 * (100-changed_rows))
    if passes:
        assert surface_change(before, after)['visual_identification'] == 'NOT TESTED'
    else:
        with pytest.raises(AssertionError, match='did not visibly change'):
            surface_change(before, after)


def test_shell_change_rejects_changed_dimensions(tmp_path):
    before, after = tmp_path / 'before.ppm', tmp_path / 'after.ppm'
    before.write_bytes(b'P6\n1 1\n255\n' + b'\x00'*3)
    after.write_bytes(b'P6\n2 1\n255\n' + b'\x00'*6)
    with pytest.raises(AssertionError, match='Display size changed'):
        surface_change(before, after)
