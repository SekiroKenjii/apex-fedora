import importlib.util
import tarfile
from pathlib import Path
import pytest
from apexlib import pipeline
from apexlib.common import ROOT, Blocked


def test_source_export_excludes_local_instructions(tmp_path):
    target = tmp_path / 'source.tar'
    result = pipeline.export_source(target)
    with tarfile.open(target) as archive:
        names = archive.getnames()
    assert 'Containerfile' in names
    assert all('AGENTS.md' not in x and '__pycache__' not in x for x in names)
    assert len(result['files']) == len(names)


def test_live_cannot_change_core_packages():
    spec = importlib.util.spec_from_file_location('parity', ROOT / 'guest/live-parity.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.compare('kernel 1 x86_64\n', 'kernel 2 x86_64\n')['status'] == 'FAIL'
    assert module.compare('kernel 1 x86_64\n', 'kernel 1 x86_64\ndracut-live 1 x86_64\n')['status'] == 'PASS'
    assert module.compare('', 'amd-gpu-firmware 1 noarch\n')['status'] == 'FAIL'


def test_installer_requires_manual_storage_and_enforcing_selinux():
    recipe = (ROOT / 'guest/disk-artifact.sh').read_text()
    boot = (ROOT / 'guest/installer-iso.yaml').read_text()
    setup = (ROOT / 'guest/installer-configure.sh').read_text()
    assert 'image_type=bootc-generic-iso' in recipe
    assert '--bootc-installer-payload-ref "$tag"' in recipe
    assert 'enforcing=1' in boot and 'enforcing=0' not in boot and 'selinux=0' not in boot
    assert 'inst.ks=' not in boot
    for directive in ('clearpart', 'zerombr', 'autopart', 'ignoredisk', 'reqpart'):
        assert directive not in setup
    assert '--source-imgref dir:/usr/share/apex/payload --target-imgref {source}' in setup


def test_installer_console_uses_pam_and_expected_generator_target():
    setup = (ROOT / 'guest/installer-configure.sh').read_text()
    assert 'ln -sfn /lib/systemd/system/anaconda.target /etc/systemd/system/default.target' in setup
    assert 'anaconda.service anaconda-tmux@.service' in setup
    pam = (ROOT / 'guest/installer-pam.conf').read_text()
    assert 'User=root' in pam and 'PAMName=login' in pam
    assert 'SELinuxContext=' not in pam
    shell = (ROOT / 'guest/installer-shell.conf').read_text()
    assert 'ExecStart=\n' in shell and '--autologin root' in shell
    assert '/bin/bash' not in shell
    assert 'StandardInput=null' in (ROOT / 'guest/installer-pre.conf').read_text()
    for name in ('installer-start.conf', 'installer-attach.conf'):
        command = (ROOT / 'guest' / name).read_text()
        assert 'ExecStart=\n' in command
        assert "ExecStart=/usr/bin/bash -c 'exec /usr/bin/tmux " in command


def test_installer_exposes_manual_user_creation_without_root_password():
    import configparser
    settings = configparser.ConfigParser()
    settings.read(ROOT / 'guest/installer-ui.conf')
    hidden = settings['User Interface']['hidden_spokes'].split()
    assert hidden == ['NetworkSpoke', 'PasswordSpoke']
    setup = (ROOT / 'guest/installer-configure.sh').read_text()
    assert '/etc/anaconda/conf.d/90-apex-ui.conf' in setup
    assert "configuration.set_from_detected_profile('fedora', 'silverblue')" in setup
    assert "assert 'UserSpoke' not in configuration.ui.hidden_spokes" in setup
    assert 'guest/installer-ui.conf' in (ROOT / 'guest/installer.Containerfile').read_text()
