"""The justfile rendered from the registry, so a recipe can never name a command that is gone.

Three kinds of recipe: the ones the commands declare, rendered as the package's entry point
with each parameter quoted; the gate and its tools, the same on every machine; and the older
tools' recipes, kept word for word until the older tree is deleted. The operator's surface
may grow and never shift, which the surface contract holds against the frozen baseline; a
recipe whose work folded into another keeps its operands and runs the retired name, so the
dispatcher's refusal names the replacement at the prompt.
"""

from __future__ import annotations

import re

from apex.cli import commands, commandspecs

PYTHON = "3.14.4"
INDENT = "    "
PLACEHOLDER = re.compile(r"\{\{([a-z_]+)\}\}")
UV = "uv run --no-project --python {{python}}"
PYTEST = f"{UV} --with pytest==9.1.1 pytest"
MIGRATION = f"{UV} python tools/migration"
LEGACY = "python3 tools/apex.py"
HEADER = (
    'set shell := ["bash", "-eu", "-o", "pipefail", "-c"]\n'
    'export PYTHONDONTWRITEBYTECODE := "1"\n'
    "\n"
    f'python := env_var_or_default("APEX_PYTHON", "{PYTHON}")\n'
    'apex := "PYTHONPATH=src uv run --no-project --python " + python'
    ' + " python -m apex.cli.main"\n'
    "\n"
    "default:\n"
    f"{INDENT}@just --list\n"
)
Lines = tuple[str, ...]
Plain = tuple[str, str, Lines]

OLDER_TOOLS: tuple[Plain, ...] = (
    ("observe-fingerprint", "", ("bash tools/observe-fingerprint.sh",)),
    ("test-fingerprint-dialog", "source",
     ('python3 tools/test-fingerprint-dialog.py "{{source}}"',)),
    ("builder-compact", "", ("python3 tools/compact-builder.py --replace-verified",)),
    ("builder-finalize", "compaction_id",
     ('python3 tools/compact-builder.py --replace-verified --resume "{{compaction_id}}"',)),
    ("build-fingerprint-rpms", "", ("python3 tools/build-fingerprint-rpms.py",)),
    ("test-fingerprint-rpms", "build_id",
     ('python3 tools/test-fingerprint-rpms.py "{{build_id}}"',)),
    ("test-fingerprint-gtk", "build_id", ('python3 tools/test-fingerprint-gtk.py "{{build_id}}"',)),
    ("build-fingerprint-image", "parent_build rpm_build gtk_test",
     ('python3 tools/build-fingerprint-image.py "{{parent_build}}" "{{rpm_build}}" '
      '"{{gtk_test}}"',)),
    ("test-elan-diagnostics", "source", ('python3 tools/test-elan-diagnostics.py "{{source}}"',)),
    ("update-fixtures", "build_id", ('python3 tools/prepare-update-fixture.py "{{build_id}}"',)),
    ("recovery-disk", "fixture", ('python3 tools/build-recovery-disk.py "{{fixture}}"',)),
    ("test-update", "action fixture access",
     ('python3 tools/update-vm.py "{{action}}" "{{fixture}}" "{{access}}"',)),
    ("test-recovery", "action fixture access",
     ('python3 tools/recovery-vm.py "{{action}}" "{{fixture}}" "{{access}}"',)),
    ("test-initramfs-inspect", "fixture access",
     ('python3 tools/initramfs-vm.py inspect "{{fixture}}" "{{access}}"',)),
    ("test-initramfs-inject", "fixture access inspection",
     ('python3 tools/initramfs-vm.py inject "{{fixture}}" "{{access}}" '
      '--inspection "{{inspection}}"',)),
    ("test-initramfs-rescue", "fixture access",
     ('python3 tools/initramfs-vm.py verify-rescue "{{fixture}}" "{{access}}"',)),
)

FOLDED: tuple[Plain, ...] = (
    ("installer-logs-collect", "run_directory token",
     ('{{apex}} installer-logs collect --run "{{run_directory}}" --token "{{token}}"',)),
)

TOOLING: tuple[Plain, ...] = (
    ("test", "", (f"{UV} python tools/check_static.py", PYTEST)),
    ("test-integration", "", (f"{PYTEST} -m integration",)),
    ("runtime-freeze", "", (f"{MIGRATION}/runtime_inventory.py record",)),
    ("runtime-verify", "", (f"{MIGRATION}/runtime_inventory.py verify",)),
    ("golden-freeze", "scratch",
     (f'PYTHONPATH=tools {MIGRATION}/golden_corpus.py record --scratch "{{{{scratch}}}}"',)),
    ("golden", "scratch",
     (f'PYTHONPATH=tools {MIGRATION}/golden_corpus.py verify --scratch "{{{{scratch}}}}"',)),
    ("surface-freeze", "scratch",
     (f'{MIGRATION}/surface_contract.py freeze --scratch "{{{{scratch}}}}"',)),
    ("surface", "", (f"{MIGRATION}/surface_contract.py check",)),
    ("ratchet-freeze", "", (f"{MIGRATION}/lint_ratchet.py freeze",)),
    ("ratchet", "", (f"{MIGRATION}/lint_ratchet.py check",)),
    ("types", "", (f"{UV} --with mypy==1.18.2 mypy --strict src/apex",)),
    ("pyright", "", (
        f"{UV} --with pytest==9.1.1 --with pyright==1.1.407 sh -c "
        "'pyright --pythonpath \"$(command -v python)\"'",
    )),
    ("deadcode", "", (
        f"{UV} --with vulture==2.14 vulture src/apex tools/migration tests/unit tests/pipelines "
        "tests/architecture tests/contract tests/property tests/support tests/integration "
        "--min-confidence 80",
    )),
    ("agent-wheel", "out", (f'{MIGRATION}/agent_wheel.py "{{{{out}}}}"',)),
    ("plans-freeze", "", (f"{MIGRATION}/golden_plans.py freeze",)),
    ("plans", "", (f"{MIGRATION}/golden_plans.py check",)),
    ("os-freeze", "", (f"{MIGRATION}/generated_os.py freeze",)),
    ("os", "", (f"{MIGRATION}/generated_os.py check",)),
    ("justfile-freeze", "", (f"{MIGRATION}/generated_justfile.py freeze",)),
    ("justfile", "", (f"{MIGRATION}/generated_justfile.py check",)),
    ("benchmarks", "", (f"{PYTEST} -q -m benchmark --durations=5",)),
    ("lint", "", (
        f"{UV} --with ruff==0.14.5 ruff check --no-cache src tools/migration tests/unit "
        "tests/pipelines tests/architecture tests/contract tests/property tests/support",
    )),
    ("readiness-shadow", "", (f"{MIGRATION}/readiness_shadow.py",)),
    ("guard-shadow", "", (f"{MIGRATION}/guard_shadow.py --self-test",)),
)
GATE: Lines = (
    "just test", "just lint", "just types", "just pyright", "just deadcode", "just plans",
    "just os", "just justfile", "just runtime-verify", "just readiness-shadow",
    "just verify-chain", "just readiness-table", "just guard-shadow", "just test-integration",
    "just surface", "just ratchet", "just benchmarks", f"{PYTEST} -q -m golden",
)


def render() -> str:
    """The whole justfile: the header, every command's recipes, the older tools, the gate."""
    sections = [
        HEADER,
        *(_command_recipe(recipe) for command in _commands() for recipe in command.recipes),
        *(_plain(name, parameters, lines) for name, parameters, lines in FOLDED),
        *(_plain(name, parameters, lines) for name, parameters, lines in OLDER_TOOLS),
        *(_plain(name, parameters, lines) for name, parameters, lines in TOOLING),
        _plain("gate", "", GATE),
    ]
    return "\n".join(sections)


def _commands() -> tuple[commandspecs.Command, ...]:
    registered = commands.sealed()
    return tuple(registered.lookup(name) for name in commands.names())


def _command_recipe(recipe: commandspecs.Recipe) -> str:
    names = {_bare(parameter) for parameter in recipe.parameters}
    words = []
    for token in recipe.argv:
        found = PLACEHOLDER.fullmatch(token)
        if found is not None and found.group(1) not in names:
            raise ValueError(f"{recipe.name}: {token} is not one of its parameters")
        words.append(f'"{token}"' if found is not None else token)
    return _plain(recipe.name, " ".join(recipe.parameters), ("{{apex}} " + " ".join(words),))


def _bare(parameter: str) -> str:
    return parameter.split("=", 1)[0]


def _plain(name: str, parameters: str, lines: Lines) -> str:
    head = f"{name} {parameters}:" if parameters else f"{name}:"
    return "\n".join((head, *(f"{INDENT}{line}" for line in lines))) + "\n"
