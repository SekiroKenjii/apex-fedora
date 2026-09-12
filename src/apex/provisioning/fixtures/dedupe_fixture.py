"""Sharing identical blob extents between two fixture bundles without removing a file.

The request layout and the range rules are `model/extents.py`; what is here is the fixture's
own profile: where it runs, what it demands of the builder, and what its self test proves.
"""

from __future__ import annotations

from apex.kernel import quantities

SCRATCH = "/var/tmp"
FILESYSTEM = "btrfs"
ARCHITECTURE = "x86_64"
SELF_TEST_SIZE = quantities.Mib(1)
REPORT_NAME = "result.json"
BLOB_SOURCE = "bundle/b"
BLOB_TARGET = "wrong-signed"
