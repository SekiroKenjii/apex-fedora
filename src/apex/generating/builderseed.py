"""The NoCloud seed the builder boots with: one account, one marker, no password anywhere.

The user data is what the older tool wrote as cloud-config: the builder account in the
wheel group with sudo and the host's public key, password login off, root disabled, the
builder marker written at first boot, and PackageKit disabled so nothing updates behind
a build. The meta data names the instance for its run and the host name. Both are JSON,
which cloud-init reads as YAML, encoded canonically so the seed is the same for the same key.
"""

from __future__ import annotations

from apex.config import defaults
from apex.generating import seedimage
from apex.kernel import encoding, identifiers

CLOUD_CONFIG = b"#cloud-config\n"
SHELL = "/bin/bash"
SUDO = "ALL=(ALL) NOPASSWD:ALL"
WHEEL = "wheel"


def user_data(public_key: str) -> bytes:
    document: encoding.Document = {
        "users": [
            {
                "name": defaults.BUILDER_USER,
                "groups": [WHEEL],
                "sudo": [SUDO],
                "shell": SHELL,
                "lock_passwd": True,
                "ssh_authorized_keys": [public_key],
            }
        ],
        "ssh_pwauth": False,
        "disable_root": True,
        "write_files": [
            {
                "path": defaults.BUILDER_MARKER,
                "permissions": defaults.BUILDER_MARKER_MODE,
                "content": defaults.BUILDER_MARKER_TEXT + "\n",
            }
        ],
        "runcmd": [["systemctl", "disable", "--now", defaults.PACKAGEKIT_UNIT]],
    }
    return CLOUD_CONFIG + encoding.canonical(document) + b"\n"


def meta_data(instance: identifiers.RunId) -> bytes:
    document: encoding.Document = {
        "instance-id": f"{defaults.BUILDER_INSTANCE_PREFIX}{instance}",
        "local-hostname": defaults.BUILDER_HOSTNAME,
    }
    return encoding.canonical(document) + b"\n"


def seed(public_key: str, instance: identifiers.RunId) -> bytes:
    """The seed image cloud-init mounts by its label, holding both documents."""
    return seedimage.image(
        defaults.SEED_VOLUME,
        {
            defaults.USER_DATA_NAME: user_data(public_key),
            defaults.META_DATA_NAME: meta_data(instance),
        },
    )
