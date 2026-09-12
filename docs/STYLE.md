# House style

These are the rules the code under `src/` is written to. Each rule names how it is held:
by a tool in `just gate`, by a test under `tests/architecture/`, or by review. A rule with no
check is a preference, and preferences are not listed here.

The rules apply to `src/` in full and to `tests/` where stated. The tree under `tools/` and
`guest/` is being replaced and is held only by the lint ratchet, which lets a file improve and
never regress.

## Layout of a file

A module starts with a docstring, then `from __future__ import annotations`, then imports in
three groups separated by a blank line: the standard library, third-party packages, then
`apex`. Each group is sorted by name. Module constants come next, then types, then functions.
Nothing runs at import time except declarations; a unit module ends with its one
`declare(...)` call.

Held by: ruff `I` and `E402`; `test_every_module_has_a_docstring`; discovery binds refusing
ports, so an import-time effect is an `InternalDefect`.

## Names

Modules are `lower_case_with_underscores` and are unique by their dotted name. Two modules
with the same basename in one layer are refused, because that is where `import module` starts
to mislead. Classes are `CapWords`. Functions, methods, variables and attributes are
`lower_case_with_underscores`. Constants are `UPPER_CASE`. A name says what a thing is, not
what type it has: `records`, never `record_list`.

Abbreviations are limited to terms of art that are already names in their own right: `argv`,
`qmp`, `ssh`, `rpm`, `oci`, `vm`. Registered units carry their kind as a suffix: `*_check.py`,
`*_rule.py`, `*_hook.py`, `*_reader.py`, `*_release.py`, `*_stage.py`, `*_recipe.py`.

Held by: ruff `N`; `test_module_basenames_are_unique_within_a_layer`;
`test_registered_units_carry_their_kind_as_a_suffix`.

## Imports

Import the module, not the name: `from apex.model import release` and then
`release.ReleaseProfile`. This keeps every reference traceable to its module at the point of
use and keeps two modules from exporting the same name into one namespace.

Two exceptions. Anything from `typing` and `collections.abc` may be imported by name. And a
type may be imported by name when a class in the importing module has a field with the same
name as the type's module, since the field would shadow the module inside the class body. The
exceptions in force are listed in `test_name_imports_are_limited_to_the_declared_exceptions`,
and adding one means adding a line there with the field that forces it.

Relative imports are not used.

Held by: ruff `TID`; the test named above.

## Types

Every function and method in `src/` and `tests/` is fully annotated, and two checkers are
clean: `mypy --strict` over `src/apex`, and pyright in standard mode over `src/`,
`tools/migration/` and the test tiers the new tree owns. Pyright is the engine the editor
runs, so a finding shown while editing is a finding the gate would report, and the gate
never passes what the editor marks. `Any` is confined to the JSON boundary and to the one
factory that hands out the refusing double; each remaining `Any` has a reason beside it.
`cast` is not used to silence the checker. Value types are `dataclass(frozen=True, slots=True)`.
A class holds mutable state only when that is its whole purpose (`Registry`, `FactMap`,
`Ledger`), and then it says so in its docstring.

A port is a `Protocol` whose members are marked `@abstractmethod`. Every adapter, real or
fake, inherits the port it implements, so a signature that drifts is reported at the class
and an adapter missing a member is refused at instantiation, instead of being discovered
wherever the adapter is passed. Anything that satisfies a port without inheriting it, such
as the refusing double or a legacy object, still passes structurally. Protocol methods whose
callers pass the argument positionally declare it positional-only, so a callable field can
stand in for the method.

Held by: `just types`; `just pyright`; `test_every_adapter_inherits_the_port_it_implements`.

## Functions

A function has at most 40 statements and a cyclomatic complexity of at most 8. Arguments after
the second of the same type are keyword-only. Mutable defaults are not used. A function returns
one type; a closed union counts as one type. Inside a stage's `apply`, an exception is never
used to steer control flow; the result is a member of `StageResult`.

Held by: ruff `C901` and `PLR0915`, configured in `pyproject.toml`; ruff `B006`.

## Docstrings

Every module has a docstring. A class or public function has one when its name and signature
do not already say what it does. A docstring describes the thing as it is: what it holds, what
it guarantees, what it refuses. It does not describe the code it replaced, the count of call
sites that used to exist, or how things were before. That history belongs in
`docs/MIGRATION.md`, where it can be read with its dates.

The shape is a one-line summary, a blank line, and a paragraph if one is needed. `Args:`,
`Returns:` and `Raises:` sections appear only when the signature does not already answer them,
which for a fully typed function is rare.

Held by: `test_every_module_has_a_docstring`;
`test_docstrings_and_comments_describe_the_tree_as_it_is`, which refuses a short list of
phrases that only ever narrate a comparison with older code.

## Comments

A comment explains a why that cannot be read from the code: an ordering constraint, a hazard,
a deliberate deviation. It never restates the line below it, never draws a separator, and never
holds code. There are no `TODO` markers; open work is an issue. A comment that carries a policy
(a threshold, a version, an exemption) is a defect, because the policy belongs in a typed field
where a test can reach it.

Held by: ruff `ERA`; `test_comment_lines_stay_within_the_budget`, which caps the count of
comment lines in `src/` so that growth is a visible decision.

## Errors

`assert` does not appear in `src/`, because `python -O` removes it. `except Exception` appears
only where a finaliser is released. `InternalDefect` is never caught. Every `Refusal` carries a
`RefusalReason` and, where the operator can act, a `remedy`. A declaration fault found at seal
time is a `RegistrationError`, not a `Refusal`.

Held by: `test_no_assert_statement_survives_in_the_package`; review for the rest.

## Input and output

`print` appears only in `cli/rendering.py`. Standard output carries one machine-readable
document; narration goes to standard error. The modules `subprocess`, `socket`, `time`, `uuid`,
`tempfile`, `shutil` and `fcntl` are imported only under `adapters/`.

Held by: `test_print_is_confined_to_rendering`;
`test_the_pure_layers_never_reach_for_an_effect_module`.

## Constants and configuration

A timeout, a size, a port, a path, a package name or a dist tag is not written as a bare
literal outside `config/defaults.py`, a profile unit under `targeting/`, or a pin file. Version
literals (`fc44`, `fedora-44`, `GNOME 50`) appear only under `targeting/releases/` and
`config/pins/`.

Held by: `test_version_literals_live_only_in_targeting_and_pins`; review for the rest.

## Formatting

The ruff formatter, line length 100, four-space indentation, double quotes, trailing commas in
multi-line constructs. The width is wider than the reference style this document was derived
from; the project's type names are long and 80 columns forced wrapping that hid the shape of a
call. Running prose in docstrings wraps at the same width.

Held by: `just lint` in check mode.

## External organisations

No file in the project names an external organisation. The one exception is a package
coordinate: an upstream package name that happens to carry one is data pointing at that
upstream, not an attribution, and it is allowed only in that exact form.

Held by: the repository content rule `repository.vendor-attribution`, which refuses any
tracked file that carries the name outside a package coordinate.

## Enforcement

`just gate` runs the formatter in check mode, ruff, `mypy --strict`, pyright, the lint ratchet, dead
code detection, the architecture tests, and every test in this document. No rule runs in a
warning mode. A new rule arrives with its check and with the fix for every existing
violation, in one change.
