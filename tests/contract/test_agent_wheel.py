"""The guest program installs from a wheel built off the tracked tree and answers from there.

This is the one place the packaging is proved: the console script exists after install, the
handshake names the protocol, and a request for the state probe is answered by a unit that
discovery found inside site-packages, not in a checkout.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from apex.model import agentwire
from migration import agent_wheel

pytestmark = pytest.mark.skipif(shutil.which("uv") is None, reason="NOT TESTED: uv is absent")


@pytest.fixture(scope="module")
def installed(tmp_path_factory: pytest.TempPathFactory) -> Path:
    base = tmp_path_factory.mktemp("agent-wheel")
    wheel = agent_wheel.build(base / "dist")
    venv = base / "venv"
    subprocess.run(["uv", "venv", "-q", str(venv)], check=True, capture_output=True)
    subprocess.run(
        ["uv", "pip", "install", "-q", "--python", str(venv / "bin" / "python"), str(wheel)],
        check=True,
        capture_output=True,
    )
    return venv / "bin" / "apex-agent"


def test_the_wheel_is_named_by_its_digest(tmp_path: Path) -> None:
    wheel = agent_wheel.build(tmp_path / "dist")

    assert wheel.suffix == ".whl"
    assert len(agent_wheel.digest_of(wheel)) == 64


def test_the_installed_guest_answers_the_handshake(installed: Path) -> None:
    completed = subprocess.run([str(installed), "handshake"], capture_output=True, check=True)

    document = json.loads(completed.stdout)
    assert document["protocol"] == agentwire.PROTOCOL_VERSION
    assert document["agent_version"] != "source"


def test_the_installed_guest_runs_a_unit_found_in_site_packages(installed: Path) -> None:
    request = json.dumps(
        {
            "protocol": agentwire.PROTOCOL_VERSION,
            "host_version": "0.2.0",
            "unit": "guest.state",
            "arguments": {},
            "agent_digest": "a" * 64,
        }
    ).encode()

    completed = subprocess.run(
        [str(installed), "run"], input=request, capture_output=True, check=True, timeout=120
    )

    reply = json.loads(completed.stdout)
    assert reply["unit"] == "guest.state"
    assert reply["observations"]["visual_test"] == "NOT TESTED"
    assert set(reply["observations"]["observations"]) >= {"kernel", "selinux"}


def test_the_installed_guest_refuses_another_protocol(installed: Path) -> None:
    request = json.dumps({"protocol": 99}).encode()

    completed = subprocess.run([str(installed), "run"], input=request, capture_output=True)

    assert completed.returncode == 2
    assert completed.stdout == b""
    assert b"protocol-mismatch" in completed.stderr
