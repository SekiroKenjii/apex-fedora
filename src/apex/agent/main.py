"""The guest program: a handshake, a request in, a reply out, and nothing else on stdout.

Standard output carries one document, plain or framed. Every refusal goes to standard error
with the exit code its kind carries, and a fault in a unit is never dressed up as a reply.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from typing import TextIO

from apex.adapters.real import (
    real_clock,
    real_containers,
    real_digesting,
    real_files,
    real_process,
)
from apex.agent import agentports, units
from apex.kernel import distribution, encoding, errors, identifiers
from apex.model import agentwire, serialframe

PREFIX = "BLOCKED: "


def real_ports() -> agentports.AgentPorts:
    processes = real_process.SubprocessRunner()
    return agentports.AgentPorts(
        processes=processes,
        files=real_files.LocalFiles(),
        clock=real_clock.SystemClock(),
        containers=real_containers.PodmanEngine(processes),
        digests=real_digesting.CachedDigests(),
    )


def dispatch(
    request: agentwire.AgentRequest, *, ports: agentports.AgentPorts
) -> agentwire.AgentReply:
    unit = units.lookup(request.unit)
    return agentwire.AgentReply.answering(
        request, observations=unit.run(ports, arguments=request.arguments)
    )


def emit(
    reply: agentwire.AgentReply, *, framed_with: identifiers.Token | None, stream: TextIO
) -> None:
    payload = encoding.canonical(reply.document())
    if framed_with is None:
        stream.write(payload.decode() + "\n")
        return
    for line in serialframe.encode(payload, token=framed_with):
        stream.write(line.decode() + "\n")
    stream.flush()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="apex-agent")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("handshake")
    run = commands.add_parser("run")
    run.add_argument("--framed", metavar="TOKEN", default=None)
    return parser


def _run(arguments: argparse.Namespace) -> int:
    if arguments.command == "handshake":
        greeting = agentwire.handshake(distribution.installed_version())
        sys.stdout.write(encoding.canonical(greeting).decode() + "\n")
        return 0
    request = agentwire.AgentRequest.parse(sys.stdin.buffer.read())
    token = identifiers.Token(arguments.framed) if arguments.framed else None
    emit(dispatch(request, ports=real_ports()), framed_with=token, stream=sys.stdout)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(list(sys.argv[1:] if argv is None else argv))
    try:
        return _run(arguments)
    except errors.ApexError as failure:
        sys.stderr.write(f"{PREFIX}{failure}\n")
        return failure.exit_code


if __name__ == "__main__":
    sys.exit(main())
