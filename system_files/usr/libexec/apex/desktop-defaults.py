#!/usr/bin/python3
import hashlib
import json
import os
from pathlib import Path
import tempfile


def digest(data):
    return hashlib.sha256(data).hexdigest()


def replace_file(path, content):
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as f:
        f.write(content)
        temporary = f.name
    os.replace(temporary, path)


def update(config_home, state_home, theme):
    state_home.mkdir(parents=True, exist_ok=True)
    record_path = state_home / "gtk-defaults.json"
    records = json.loads(record_path.read_text()) if record_path.exists() else {}
    for version in ("gtk-3.0", "gtk-4.0"):
        directory = config_home / version
        if directory.is_symlink():
            continue
        directory.mkdir(parents=True, exist_ok=True)
        managed, entry = directory / "apex.css", directory / "gtk.css"
        if managed.is_symlink() or entry.is_symlink():
            continue
        source = theme / version / "gtk.css"
        if not source.is_file():
            continue
        if managed.exists() and digest(managed.read_bytes()) != records.get(version):
            # An existing unowned file or a user edit stays intact.
            continue
        data = source.read_bytes()
        replace_file(managed, data)
        records[version] = digest(data)
        current = entry.read_bytes() if entry.exists() else b""
        directive = b'@import url("apex.css");\n'
        if directive not in current:
            replace_file(entry, directive + current)
    replace_file(record_path, (json.dumps(records, indent=2) + "\n").encode())


if __name__ == "__main__":
    update(Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")), Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "apex", Path("/usr/share/themes/Shadcn-Graphite"))
