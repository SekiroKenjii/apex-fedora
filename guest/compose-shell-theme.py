#!/usr/bin/python3
"""Combine the installed GNOME Shell base with Apex's generated overrides."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath

PREFIX = '/org/gnome/shell/theme/'


def extract(resource):
    from gi.repository import Gio
    bundle = Gio.Resource.load(str(resource))
    files = {}

    def visit(parent):
        for child in bundle.enumerate_children(parent, Gio.ResourceLookupFlags.NONE):
            name = parent + child
            relative = name.removeprefix(PREFIX)
            path = PurePosixPath(relative)
            if not relative or path.is_absolute() or '..' in path.parts:
                raise ValueError('Invalid Shell resource path')
            if child.endswith('/'):
                visit(name)
            else:
                files[relative] = bytes(bundle.lookup_data(name, Gio.ResourceLookupFlags.NONE).get_data())

    visit(PREFIX)
    return files


def compose(files, override, destination):
    base = next((name for name in ('gnome-shell-dark.css', 'gnome-shell.css') if files.get(name)), None)
    if base is None:
        raise ValueError('The installed Shell resource has no base stylesheet')
    if not override.strip():
        raise ValueError('The Apex Shell override is empty')
    final = destination / 'gnome-shell.css'
    if final.is_symlink() or not final.resolve().is_relative_to(destination.resolve()):
        raise ValueError('Shell stylesheet output escapes its destination')
    for name, data in files.items():
        relative = PurePosixPath(name)
        if relative.is_absolute() or '..' in relative.parts or not name:
            raise ValueError('Invalid Shell resource path')
        target = destination / name
        if not target.resolve().is_relative_to(destination.resolve()) or target.is_symlink():
            raise ValueError('Shell resource output escapes its destination')
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    stylesheet = files[base] + b'\n' + override
    final.write_bytes(stylesheet)
    return {'base': base, 'base_sha256': hashlib.sha256(files[base]).hexdigest(),
            'override_sha256': hashlib.sha256(override).hexdigest(),
            'stylesheet_sha256': hashlib.sha256(stylesheet).hexdigest(), 'resources': len(files)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('resource', type=Path)
    parser.add_argument('override', type=Path)
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    print(json.dumps(compose(extract(args.resource), args.override.read_bytes(), args.destination)))
