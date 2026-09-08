#!/usr/bin/python3
import json
from pathlib import Path
import subprocess


def repair(text, available_keys):
    result = []
    section = None
    for line in text.splitlines(keepends=True):
        value = line.strip()
        if value.startswith('[') and value.endswith(']'):
            section = value[1:-1]
        if section == 'org.gnome.desktop.screensaver' and value.startswith('picture-uri-dark=') and 'picture-uri-dark' not in available_keys:
            continue
        result.append(line)
    return ''.join(result)


def main():
    path = Path('/usr/share/glib-2.0/schemas/10_org.gnome.desktop.screensaver.fedora.gschema.override')
    keys = subprocess.check_output(['gsettings', 'list-keys', 'org.gnome.desktop.screensaver'], text=True).splitlines()
    original = path.read_text()
    fixed = repair(original, keys)
    if original != fixed:
        path.write_text(fixed)
    Path('/usr/share/apex/schema-adjustments.json').write_text(json.dumps({'file': str(path), 'removed_unsupported_screensaver_dark_key': original != fixed}) + '\n')


if __name__ == '__main__':
    main()
