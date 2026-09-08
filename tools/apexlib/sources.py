from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import tarfile
import urllib.parse
import urllib.request

from .common import ROOT, Blocked, atomic_json, config, run, sha256

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


def resolve_image(ref: str) -> dict:
    registry, rest = ref.split("/", 1)
    name, tag = rest.rsplit(":", 1)
    url = f"https://{registry}/v2/{name}/manifests/{tag}"
    headers = {"Accept": "application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.list.v2+json, application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json"}
    try:
        response = urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=45)
    except urllib.error.HTTPError as exc:
        if exc.code != 401:
            raise
        fields = dict(re.findall(r'(\w+)="([^"]*)"', exc.headers.get("WWW-Authenticate", "")))
        realm = fields.pop("realm", "")
        if not realm.startswith("https://"):
            raise Blocked("Registry authentication did not supply an HTTPS token service")
        query = urllib.parse.urlencode(fields)
        token = json.load(urllib.request.urlopen(realm + "?" + query, timeout=45))
        headers["Authorization"] = "Bearer " + token.get("token", token.get("access_token", ""))
        response = urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=45)
    raw = response.read()
    digest = "sha256:" + hashlib.sha256(raw).hexdigest()
    advertised = response.headers.get("Docker-Content-Digest")
    if advertised and advertised != digest:
        raise Blocked("Registry digest mismatch")
    return {"reference": f"{registry}/{name}@{digest}", "digest": digest, "verified_boot": False}


def acquire(directory: Path):
    pinned = ROOT / "config/sources.lock.json"
    if pinned.exists():
        lock = json.loads(pinned.read_text())
        for name, source in lock["sources"].items():
            filename = source.get("filename", f"{name}.tar.gz")
            if Path(filename).name != filename:
                raise Blocked("Source filename must not contain directories")
            download(source["url"], directory / "sources" / filename, source["sha256"])
        atomic_json(directory / "sources.lock.json", lock)
        return lock
    cfg = config()
    target = directory / "sources"
    target.mkdir(parents=True, exist_ok=True)
    lock = {"schema": 1, "base": resolve_image(cfg["base"]), "image_builder": resolve_image(cfg["image_builder"]), "sources": {}}
    for name, source in cfg["sources"].items():
        slug = source["repository"].removeprefix("https://github.com/")
        url = f"https://codeload.github.com/{slug}/tar.gz/{source['commit']}"
        path = target / f"{name}.tar.gz"
        download(url, path)
        lock["sources"][name] = {**source, "url": url, "sha256": sha256(path)}
    for name, repository in (("titanoboa", "ublue-os/titanoboa"), ("greenboot-rs", "fedora-iot/greenboot-rs")):
        req = urllib.request.Request(f"https://api.github.com/repos/{repository}/commits/main", headers={"User-Agent": "apex-build"})
        commit = json.load(urllib.request.urlopen(req, timeout=45))["sha"]
        url = f"https://codeload.github.com/{repository}/tar.gz/{commit}"
        path = target / f"{name}.tar.gz"
        download(url, path)
        lock["sources"][name] = {"repository": f"https://github.com/{repository}", "commit": commit, "url": url, "sha256": sha256(path)}
    atomic_json(directory / "sources.lock.json", lock)
    return lock


def extract(archive: Path, destination: Path):
    with tarfile.open(archive) as tar:
        tar.extractall(destination, filter="data")
