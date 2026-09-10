#!/usr/bin/python3
"""Display native controls for visual theme acceptance in a disposable guest."""
import json
import sys
import gi

mode = sys.argv.pop(1)
if mode not in {'gtk3', 'adwaita'}:
    raise ValueError('Select gtk3 or adwaita')
gi.require_version('Gtk', '3.0' if mode == 'gtk3' else '4.0')
if mode == 'adwaita':
    gi.require_version('Adw', '1')
    from gi.repository import Adw
from gi.repository import Gtk, Gdk


def activate(app):
    window_type = Gtk.ApplicationWindow if mode == 'gtk3' else Adw.ApplicationWindow
    window = window_type(application=app, title=f'Apex theme: {mode}')
    window.set_default_size(600, 440)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
    for direction in ('top', 'bottom', 'start', 'end'):
        getattr(box, f'set_margin_{direction}')(24)
    widgets = [Gtk.Label(label=f'Native {mode} controls'),
               Gtk.Label(label='Check the window background, text and control borders.'),
               Gtk.Entry(text='Editable sample text'),
               Gtk.Button(label='Sample button'),
               Gtk.CheckButton(label='Sample selection', active=True),
               Gtk.Switch(active=True, halign=Gtk.Align.START),
               Gtk.ProgressBar(fraction=.6)]
    for widget in widgets:
        if mode == 'gtk3':
            box.pack_start(widget, False, False, 0)
        else:
            box.append(widget)
    if mode == 'gtk3':
        bar = Gtk.HeaderBar(title='Apex GTK3', show_close_button=True)
        window.set_titlebar(bar)
        window.add(box)
        window.show_all()
    else:
        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(Adw.HeaderBar())
        toolbar.set_content(box)
        window.set_content(toolbar)
    window.present()
    print(json.dumps({'mode': mode, 'event': 'window-presented',
                      'display_type': Gdk.Display.get_default().__gtype__.name}), flush=True)


app_type = Gtk.Application if mode == 'gtk3' else Adw.Application
app = app_type(application_id=f'dev.apex.Theme{mode}')
app.connect('activate', activate)
app.run()
