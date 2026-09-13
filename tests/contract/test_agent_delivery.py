"""The guest program answers from an unpacked wheel with nothing installed.

Delivery unpacks the wheel with the interpreter's archive module and runs the agent as a
module off that directory. This proves that path on the host, where the wheel can be built.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from apex.kernel import identifiers
from apex.model import agentwire, serialframe
from migration import agent_wheel

pytestmark = pytest.mark.skipif(shutil.which("uv") is None, reason="NOT TESTED: uv is absent")
TOKEN = identifiers.Token("e" * 32)


@pytest.fixture(scope="module")
def library(tmp_path_factory: pytest.TempPathFactory) -> Path:
    base = tmp_path_factory.mktemp("agent-delivery")
    wheel = agent_wheel.build(base / "dist")
    target = base / "agent" / "lib"
    subprocess.run(
        [sys.executable, "-m", "zipfile", "-e", str(wheel), str(target)],
        check=True,
        capture_output=True,
    )
    return target


def test_the_unpacked_agent_answers_the_handshake(library: Path) -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "apex.agent.main", "handshake"],
        env={"PYTHONPATH": str(library), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        check=True,
    )

    assert json.loads(completed.stdout)["protocol"] == agentwire.PROTOCOL_VERSION


def test_the_unpacked_agent_runs_a_unit_and_frames_the_reply(library: Path) -> None:
    request = json.dumps(
        {
            "protocol": agentwire.PROTOCOL_VERSION,
            "host_version": "source",
            "unit": "guest.state",
            "arguments": {},
            "agent_digest": "a" * 64,
        }
    ).encode()

    completed = subprocess.run(
        [sys.executable, "-m", "apex.agent.main", "run", "--framed", str(TOKEN)],
        input=request,
        env={"PYTHONPATH": str(library), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        check=True,
        timeout=120,
    )

    payload = serialframe.decode_lines(completed.stdout.splitlines(), token=TOKEN)
    reply = agentwire.AgentReply.parse(payload)
    assert str(reply.unit) == "guest.state"
    assert reply.observations["visual_test"] == "NOT TESTED"
