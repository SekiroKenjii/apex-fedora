#!/usr/bin/python3
"""A visible GTK4 test window; a screenshot must confirm its rendered swatches."""
import json
import gi

gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Gdk


def draw(area, context, width, height):
    for index, color in enumerate(((0.9, 0.15, 0.15), (0.15, 0.75, 0.25), (0.15, 0.3, 0.9))):
        context.set_source_rgb(*color)
        context.rectangle(index * width / 3, 0, width / 3, height)
        context.fill()


class Probe(Gtk.Application):
    def do_activate(self):
        window = Gtk.ApplicationWindow(application=self, title='Apex render probe')
        window.set_default_size(640, 360)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        box.set_margin_top(24)
        box.set_margin_bottom(24)
        box.set_margin_start(24)
        box.set_margin_end(24)
        box.append(Gtk.Label(label='Apex: password login and GTK4 rendering'))
        box.append(Gtk.Label(label='The three swatches must be visible in the VM screenshot.'))
        area = Gtk.DrawingArea()
        area.set_vexpand(True)
        area.set_draw_func(draw)
        box.append(area)
        window.set_child(box)
        window.present()
        print(json.dumps({'event': 'window-presented', 'display_type': Gdk.Display.get_default().__gtype__.name}), flush=True)


Probe(application_id='dev.apex.RenderProbe').run()
