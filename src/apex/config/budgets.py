"""The sizes the architecture is held to: one number each, read by the tests and the checks.

A module, a function and a package each have a ceiling, and a module outside the kernel a
ceiling on how many modules may import it. The numbers are the specification's where it
gives one and the phase log's decision where the specification is silent.
"""

from __future__ import annotations

from collections.abc import Mapping

MODULE_LINE_LIMIT = 400
FUNCTION_STATEMENT_LIMIT = 40
FUNCTION_COMPLEXITY_LIMIT = 8
FAN_IN_LIMIT = 40
COMMENT_LINE_BUDGET = 40
FAN_IN_EXEMPT: tuple[str, ...] = (
    "apex.kernel",
    "apex.config.defaults",
    "apex.ports.portset",
    "apex.agent.agentports",
    "apex.pipeline.stages",
    "apex.pipeline.effects",
    "apex.composition.keys",
    "apex.verification.verifykeys",
    "apex.ports.guestshell",
)
PACKAGE_LINE_BUDGETS: Mapping[str, int] = {
    "kernel": 1500,
    "assets": 100,
    "model": 1900,
    "ports": 1100,
    "registry": 800,
    "pipeline": 1200,
    "config": 900,
    "targeting": 600,
    "attestation": 3600,
    "composition": 2600,
    "verification": 8000,
    "generating": 800,
    "provisioning": 2500,
    "trust": 1200,
    "agent": 6400,
    "workspace": 2400,
    "adapters": 3100,
    "cli": 3700,
    "wiring": 300,
}
