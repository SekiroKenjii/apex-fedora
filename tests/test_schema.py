import importlib.util
from apexlib.common import ROOT

spec = importlib.util.spec_from_file_location('overrides', ROOT / 'guest/fix-schema-overrides.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

TEXT = "[org.gnome.desktop.screensaver]\npicture-uri='day'\npicture-uri-dark='night'\n[other.schema]\npicture-uri-dark='other'\n"


def test_only_unsupported_screensaver_key_is_removed():
    result = module.repair(TEXT, ['picture-uri'])
    assert "picture-uri='day'" in result
    assert "picture-uri-dark='night'" not in result
    assert "picture-uri-dark='other'" in result


def test_supported_key_is_kept():
    assert module.repair(TEXT, ['picture-uri', 'picture-uri-dark']) == TEXT
