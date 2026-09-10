from __future__ import annotations

import json
from pathlib import Path
import re
import tarfile

from .common import ROOT, Blocked, atomic_json, regular_file, run, sha256

def download(url: str, destination: Path, expected: str | None = None):
    if not url.startswith("https://"):
        raise Blocked("Source downloads require HTTPS")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and expected and sha256(destination) == expected:
        return
    temporary = destination.with_suffix(destination.suffix + ".part")
    run(["curl", "--fail", "--location", "--proto", "=https", "--proto-redir", "=https", "--retry", "2", "--connect-timeout", "20", "--max-time", "1200", "--output", temporary, url])
    if expected and sha256(temporary) != expected:
        raise Blocked(f"Checksum mismatch: {destination.name}; partial download retained for inspection")
    temporary.replace(destination)


def validate_lock(lock):
    if not isinstance(lock, dict) or type(lock.get('schema')) is not int or lock['schema'] != 1:
        raise Blocked('Unsupported source lock schema')
    for name in ('base', 'image_builder'):
        image = lock.get(name)
        if not isinstance(image, dict):
            raise Blocked(f'Missing locked image: {name}')
        reference, digest = image.get('reference'), image.get('digest')
        if not isinstance(digest, str) or not re.fullmatch('sha256:[a-f0-9]{64}', digest):
            raise Blocked(f'Invalid locked image digest: {name}')
        if not isinstance(reference, str) or not re.fullmatch(r'[^\s@]+@' + digest, reference):
            raise Blocked(f'Image reference must match its locked digest: {name}')
    sources = lock.get('sources')
    if not isinstance(sources, dict) or not sources:
        raise Blocked('The source lock needs archive entries')
    filenames = set()
    for name, source in sources.items():
        if not isinstance(name, str) or not isinstance(source, dict):
            raise Blocked('Invalid source archive entry')
        checksum, url = source.get('sha256'), source.get('url')
        if not isinstance(checksum, str) or not re.fullmatch('[a-f0-9]{64}', checksum):
            raise Blocked(f'Missing or invalid source checksum: {name}')
        if not isinstance(url, str) or not url.startswith('https://'):
            raise Blocked(f'Source downloads require HTTPS: {name}')
        if 'commit' in source and (not isinstance(source['commit'], str) or
                                   not re.fullmatch('[a-f0-9]{40}|[a-f0-9]{64}', source['commit'])):
            raise Blocked(f'Source commit must be a full object ID: {name}')
        filename = source.get('filename', f'{name}.tar.gz')
        if not isinstance(filename, str) or not re.fullmatch('[A-Za-z0-9_.-]+', filename) or filename in {'.', '..'}:
            raise Blocked('Source filename must be a plain basename')
        if filename in filenames:
            raise Blocked('Source archive filenames must be distinct')
        filenames.add(filename)


def acquire(directory: Path):
    pinned = ROOT / "config/sources.lock.json"
    if not pinned.exists():
        raise Blocked('Source lock is missing; restore the reviewed config/sources.lock.json')
    regular_file(pinned, within=ROOT)
    try:
        lock = json.loads(pinned.read_text())
    except (OSError, ValueError) as exc:
        raise Blocked('Cannot read the reviewed source lock') from exc
    # Validate every entry before a network request or a cache replacement.
    validate_lock(lock)
    for name, source in lock['sources'].items():
        filename = source.get('filename', f'{name}.tar.gz')
        download(source['url'], directory / 'sources' / filename, source['sha256'])
    atomic_json(directory / "sources.lock.json", lock)
    return lock


def extract(archive: Path, destination: Path):
    with tarfile.open(archive) as tar:
        tar.extractall(destination, filter="data")
