"""Read which themes and extensions the session has and how the Shell theme was composed."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from apex.agent import agentports, desktopprobing, guestguard, observing, units
from apex.config import defaults
from apex.kernel import commands, encoding, identifiers, safepaths

SCOPE = "theme settings of the logged-in session, read and never judged here"
COMMANDS: Mapping[str, commands.Argv] = {
    "gtk_theme": commands.Argv.of("gsettings", "get", "org.gnome.desktop.interface", "gtk-theme"),
    "shell_theme": commands.Argv.of(
        "gsettings", "get", "org.gnome.shell.extensions.user-theme", "name"
    ),
    "extensions": commands.Argv.of("gnome-extensions", "list", "--enabled"),
}


def run(
    ports: agentports.AgentPorts,
    *,
    arguments: Mapping[str, encoding.JsonValue],  # noqa: ARG001
) -> encoding.Document:
    # The settings probe takes no arguments; the shape is the unit contract and every unit keeps it.
    guestguard.require_shell_session(ports)
    return {
        "scope": SCOPE,
        "visual_review": desktopprobing.NOT_TESTED,
        "settings": observing.programs(ports, COMMANDS),
        "composition": observing.text(ports, safepaths.SafePath(Path(defaults.SHELL_THEME_SOURCE))),
    }


units.declare(units.Unit(id=identifiers.ProbeId("desktop.theme-settings"), run=run))
