"""The builder's seed carries one account with the host's key, the marker, and no password."""

from __future__ import annotations

import json

from apex.generating import builderseed
from apex.kernel import identifiers

KEY = "ssh-ed25519 AAAA host"
RUN = identifiers.RunId("a" * 32)


def test_user_data_is_cloud_config_with_the_builder_account_and_the_marker() -> None:
    payload = builderseed.user_data(KEY)

    assert payload.startswith(b"#cloud-config\n")
    document = json.loads(payload[len(b"#cloud-config\n"):])
    user = document["users"][0]
    assert user["name"] == "builder" and "wheel" in user["groups"]
    assert user["ssh_authorized_keys"] == [KEY] and user["lock_passwd"] is True
    assert user["sudo"] == ["ALL=(ALL) NOPASSWD:ALL"]
    assert document["ssh_pwauth"] is False and document["disable_root"] is True
    assert document["write_files"] == [{
        "path": "/etc/apex-builder", "permissions": "0600", "content": "apex-isolated-builder-v1\n",
    }]
    assert document["runcmd"] == [["systemctl", "disable", "--now", "packagekit.service"]]
    assert b"password" not in payload


def test_meta_data_names_the_instance_for_its_run_and_the_host() -> None:
    assert json.loads(builderseed.meta_data(RUN)) == {
        "instance-id": f"apex-builder-{RUN}", "local-hostname": "apex-builder",
    }


def test_the_seed_holds_both_documents_on_the_cidata_volume() -> None:
    image = builderseed.seed(KEY, RUN)

    assert image[16 * 2048 + 40:16 * 2048 + 46] == b"cidata"
    assert builderseed.user_data(KEY) in image
    assert builderseed.meta_data(RUN) in image
    assert image == builderseed.seed(KEY, RUN)
