import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("defaults", Path(__file__).parents[1] / "system_files/usr/libexec/apex/desktop-defaults.py")
defaults = importlib.util.module_from_spec(spec)
spec.loader.exec_module(defaults)


def test_preserve_user_css_and_update_owned_styles(tmp_path):
    config, state, theme = (tmp_path / name for name in ("config", "state", "theme"))
    for root in (config, theme):
        (root / "gtk-4.0").mkdir(parents=True)
    source = theme / "gtk-4.0/gtk.css"
    source.write_text("button { color: red; }")
    entry = config / "gtk-4.0/gtk.css"
    entry.write_text("/* user style */")
    defaults.update(config, state, theme)
    assert entry.read_text().endswith("/* user style */")
    defaults.update(config, state, theme)
    assert entry.read_text().count("@import") == 1
    source.write_text("button { color: blue; }")
    defaults.update(config, state, theme)
    assert "blue" in (config / "gtk-4.0/apex.css").read_text()
    (config / "gtk-4.0/apex.css").write_text("user modified this")
    defaults.update(config, state, theme)
    assert (config / "gtk-4.0/apex.css").read_text() == "user modified this"


def test_rpm_supplies_named_dark_gtk3_base_without_copying_gtk_resources():
    root = Path(__file__).parents[1]
    alias = (root / 'rpms/gtk3-adwaita-dark.css').read_text()
    assert '@import url("resource:///org/gtk/libgtk/theme/Adwaita/gtk-contained-dark.css");' in alias
    assert len(alias.splitlines()) == 2
    spec = (root / 'rpms/shadcn-gnome-theme.spec').read_text()
    assert 'Source1: gtk3-adwaita-dark.css' in spec and 'Requires: gtk3' in spec
    assert 'install -Dm0644 %{SOURCE1}' in spec and '/themes/Adwaita-dark/gtk-3.0/gtk.css' in spec
    assert 'sources/gtk3-adwaita-dark.css' in (root / 'guest/build-rpms.sh').read_text()
