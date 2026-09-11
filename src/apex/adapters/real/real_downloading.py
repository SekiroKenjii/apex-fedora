"""Fetching over https through curl, with the pin checked before the file is settled."""

from __future__ import annotations

import subprocess

from apex.adapters import parts
from apex.config import defaults
from apex.kernel import claims, errors, identifiers, locators, safepaths, timing

PROGRAM = "curl"
TIMEOUT_GRACE_SECONDS = 5


class CurlDownloads:
    environment = claims.EnvironmentKind.BUILD

    def fetch(
        self,
        url: locators.HttpsUrl,
        *,
        into: safepaths.SafePath,
        expected: identifiers.Digest,
        deadline: timing.Deadline,
    ) -> identifiers.Digest:
        into.path.parent.mkdir(parents=True, exist_ok=True, mode=parts.PRIVATE_DIRECTORY)
        part = parts.part_of(into.path)
        arguments = [
            PROGRAM, "--fail", "--silent", "--show-error", "--location",
            "--proto", "=https", "--proto-redir", "=https",
            "--retry", str(defaults.DOWNLOAD_RETRIES),
            "--connect-timeout", str(defaults.DOWNLOAD_CONNECT_TIMEOUT.seconds),
            "--max-time", str(int(deadline.budget.seconds)),
            "--output", str(part), str(url),
        ]
        try:
            completed = subprocess.run(  # noqa: S603
                arguments,
                capture_output=True,
                timeout=deadline.budget.seconds + TIMEOUT_GRACE_SECONDS,
                check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as fault:
            part.unlink(missing_ok=True)
            raise errors.PortFailure(port="downloads", cause=str(fault)) from fault
        if completed.returncode:
            part.unlink(missing_ok=True)
            raise errors.PortFailure(
                port="downloads", cause=completed.stderr.decode(errors="replace").strip()
            )
        return parts.settle(part, into.path, expected)
