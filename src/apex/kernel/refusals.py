"""Every deliberate refusal has an identity.

Tests match a code. Prose may be reworded without breaking anything, and a differently
worded correct rejection cannot pass as a false negative.
"""

from __future__ import annotations

import enum


class RefusalReason(enum.StrEnum):
    MALFORMED_DIGEST = "malformed.digest"
    MALFORMED_IDENTIFIER = "malformed.identifier"
    MALFORMED_PACKAGE_COORDINATE = "malformed.package-coordinate"
    MALFORMED_VERDICT = "malformed.verdict"

    NEGATIVE_QUANTITY = "quantity.negative"
    PORT_OUT_OF_RANGE = "quantity.port-out-of-range"
    MODE_OUT_OF_RANGE = "quantity.mode-out-of-range"
    LIMIT_NOT_POSITIVE = "quantity.limit-not-positive"

    PATH_OUTSIDE_RUNTIME_ROOT = "path.outside-runtime-root"
    PATH_NOT_A_REGULAR_FILE = "path.not-a-regular-file"
    PATH_IS_A_SYMLINK = "path.is-a-symlink"
    PATH_CONTAINS_OPTION_SEPARATOR = "path.contains-option-separator"
    RUNTIME_ROOT_NOT_PERMITTED = "path.runtime-root-not-permitted"
    RUNTIME_ROOT_NOT_PRIVATE = "path.runtime-root-not-private"

    LINE_EXCEEDS_LIMIT = "bounded.line-exceeds-limit"

    NO_VERIFIED_RESULT = "evidence.no-verified-result"
    HARDWARE_REQUIRES_PHYSICAL = "evidence.hardware-requires-physical"
    PASS_REQUIRES_PROOF = "evidence.pass-requires-proof"
    UNKNOWN_CHECK = "evidence.unknown-check"
    DUPLICATE_EVIDENCE = "evidence.duplicate"
    STALE_EVIDENCE = "evidence.stale-or-unbound"
    PROOF_KIND_NOT_ACCEPTED = "evidence.proof-kind-not-accepted"
    SIMULATED_ENVIRONMENT = "evidence.simulated-environment"

    SHELL_STRING_NOT_ACCEPTED = "command.shell-string-not-accepted"
    DEADLINE_REQUIRED = "command.deadline-required"

    SECRET_NOT_RENDERABLE = "secret.not-renderable"

    VENDOR_ATTRIBUTION_PRESENT = "style.vendor-attribution-present"
    PROFILE_NOT_REVIEWED = "target.profile-not-reviewed"
