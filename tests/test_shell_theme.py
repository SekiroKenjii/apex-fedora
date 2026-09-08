import importlib.util
from pathlib import Path
import pytest

spec = importlib.util.spec_from_file_location('shell_theme', Path(__file__).parents[1] / 'guest/compose-shell-theme.py')
theme = importlib.util.module_from_spec(spec)
spec.loader.exec_module(theme)


def test_override_follows_complete_dark_base(tmp_path):
    files = {'gnome-shell-dark.css': b'base-dark', 'gnome-shell.css': b'base-light', 'icons/test.svg': b'<svg/>'}
    result = theme.compose(files, b'apex-overrides', tmp_path)
    assert (tmp_path / 'gnome-shell.css').read_bytes() == b'base-dark\napex-overrides'
    assert (tmp_path / 'icons/test.svg').read_bytes() == b'<svg/>'
    assert result['base'] == 'gnome-shell-dark.css'


def test_missing_base_cannot_produce_an_override_only_theme(tmp_path):
    with pytest.raises(ValueError, match='no base'):
        theme.compose({}, b'override', tmp_path)


def test_resource_cannot_escape_destination(tmp_path):
    with pytest.raises(ValueError, match='Invalid'):
        theme.compose({'../escape': b'x', 'gnome-shell.css': b'base'}, b'override', tmp_path)


def test_final_stylesheet_cannot_follow_a_symlink(tmp_path):
    outside = tmp_path / 'keep.txt'
    outside.write_bytes(b'keep')
    destination = tmp_path / 'theme'
    destination.mkdir()
    (destination / 'gnome-shell.css').symlink_to(outside)
    with pytest.raises(ValueError, match='escapes'):
        theme.compose({'gnome-shell-dark.css': b'base'}, b'override', destination)
    assert outside.read_bytes() == b'keep'
