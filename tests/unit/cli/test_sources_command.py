"""The sources command fetches the reviewed lock into the runtime root and reports each pin."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from apex.adapters.fakes import fake_downloading, fake_files
from apex.cli import commandspecs
from apex.cli.commands import sources_command
from apex.config import loader, sourcepins
from apex.kernel import errors, safepaths
from apex.ports import portset
from apex.wiring import contexts

REPOSITORY = Path(__file__).resolve().parents[3]


def request(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot | None, *arguments: str
) -> commandspecs.Request:
    return commandspecs.Request(
        arguments=arguments,
        context=contexts.Context(
            settings=loader.load(host_file=None, environment={}),
            repository=safepaths.SourceRoot.adopt(REPOSITORY),
            root=root,
            environment={},
            bundle=lambda _root: ports,
        ),
    )


def test_every_locked_source_is_fetched_against_its_pin_and_the_lock_recorded(
    ports: portset.HostPorts, tmp_path: Path
) -> None:
    base = tmp_path / "runtime"
    base.mkdir(mode=0o700)
    root = safepaths.RuntimeRoot.adopt(base)
    held = dataclasses.replace(
        ports, files=fake_files.MemoryFiles(), downloads=fake_downloading.PinningFetcher()
    )

    reply = sources_command.run(request(held, root))

    reviewed = sourcepins.load(safepaths.SourceRoot.adopt(REPOSITORY))
    assert isinstance(reply.document, dict)
    listed = reply.document["sources"]
    assert isinstance(listed, list)
    assert [item["name"] for item in listed] == [  # type: ignore[index]
        source.name for source in reviewed.lock.sources
    ]
    assert all(item["fetched"] is True for item in listed)  # type: ignore[index]
    assert held.files.exists(root.child("sources.lock.json"))
    fetcher = held.downloads
    assert isinstance(fetcher, fake_downloading.PinningFetcher)
    assert len(fetcher.fetched) == len(reviewed.lock.sources)


def test_sources_need_a_runtime_root(ports: portset.HostPorts) -> None:
    with pytest.raises(errors.PreconditionUnmet):
        sources_command.run(request(ports, None))
