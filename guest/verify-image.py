#!/usr/bin/python3
"""Static image checks, separate from boot and hardware acceptance."""
import json
import hashlib
from pathlib import Path
import re
import subprocess


def output(*args):
    return subprocess.check_output(args, text=True).strip()


def main():
    import gi
    gi.require_version('Gtk', '3.0')
    from gi.repository import Gio, Gtk
    # Load GTK3's built-in resources without requiring a display server.
    Gtk.CssProvider()
    resource = Gio.resources_lookup_data('/org/gtk/libgtk/theme/Adwaita/gtk-contained-dark.css', Gio.ResourceLookupFlags.NONE).get_data()
    alias = Path('/usr/share/themes/Adwaita-dark/gtk-3.0/gtk.css').read_bytes()
    assert b'resource:///org/gtk/libgtk/theme/Adwaita/gtk-contained-dark.css' in alias and resource
    gtk3_base = {'alias_sha256': hashlib.sha256(alias).hexdigest(), 'resource_sha256': hashlib.sha256(resource).hexdigest(), 'resource_bytes': len(resource)}
    kernels = list(Path('/usr/lib/modules').iterdir())
    assert len(kernels) == 1, 'Expected one installed kernel'
    kernel = kernels[0].name
    assert (kernels[0] / 'vmlinuz').is_file()
    assert (kernels[0] / 'initramfs.img').is_file()
    contents = output('lsinitrd', str(kernels[0] / 'initramfs.img'))
    assert 'ostree' in contents, 'Installed initramfs lacks ostree support'
    modules = {}
    for module in ('amdgpu', 'snd_hda_intel', 'nvme', 'usb_storage', 'virtio_blk', 'dm_crypt'):
        filename = output('modinfo', '-k', kernel, '-F', 'filename', module)
        if filename == '(builtin)':
            modules[module] = 'built into kernel'
        else:
            vermagic = output('modinfo', '-k', kernel, '-F', 'vermagic', module).split()
            assert vermagic and vermagic[0] == kernel, f'{module}: incorrect vermagic'
            modules[module] = filename
    version = output('gnome-shell', '--version')
    assert re.search(r'\b50[. ]', version + ' '), version
    theme = json.loads(Path('/usr/share/apex/shell-theme-source.json').read_text())
    css = Path('/usr/share/themes/Shadcn-Graphite/gnome-shell/gnome-shell.css').read_bytes()
    assert theme['resources'] > 0 and hashlib.sha256(css).hexdigest() == theme['stylesheet_sha256']
    extensions = Path('/usr/share/gnome-shell/extensions')
    for uuid in ('user-theme@gnome-shell-extensions.gcampax.github.com', 'dash-to-dock@micxgx.gmail.com', 'macos-genie@thuongvo.dev'):
        metadata = json.loads((extensions / uuid / 'metadata.json').read_text())
        assert '50' in metadata['shell-version'], uuid
    result = subprocess.run(['systemctl', 'is-enabled', 'bootc-fetch-apply-updates.timer'], capture_output=True, text=True)
    assert result.stdout.strip() == 'masked'
    fragment = Path('/usr/lib/bootupd/grub2-static/configs.d/08_greenboot.cfg').read_bytes()
    assert fragment.endswith(b'\n') and fragment.rstrip(b'\n').splitlines()[-1] == b'save_env boot_success', 'GRUB fragment requires a command separator'
    print(json.dumps({'kernel': kernel, 'gnome': version, 'modules': modules, 'shell_theme': theme, 'gtk3_base': gtk3_base, 'greenboot_fragment_sha256': hashlib.sha256(fragment).hexdigest(), 'static_checks': 'PASS', 'boot': 'NOT TESTED', 'hardware': 'NOT TESTED'}))


if __name__ == '__main__':
    main()
