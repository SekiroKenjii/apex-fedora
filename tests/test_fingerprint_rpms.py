import importlib.util
import io
import json
import subprocess
import sys
import tarfile

import pytest
from apexlib.common import ROOT, Blocked, sha256

spec = importlib.util.spec_from_file_location('fingerprint_rpms', ROOT / 'guest/fingerprint-rpms.py')
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)
runner_spec = importlib.util.spec_from_file_location('fingerprint_rpm_runner', ROOT / 'tools/build-fingerprint-rpms.py')
runner = importlib.util.module_from_spec(runner_spec)
runner_spec.loader.exec_module(runner)
smoke_spec = importlib.util.spec_from_file_location('fingerprint_rpm_smoke', ROOT / 'guest/fingerprint-rpm-smoke.py')
smoke = importlib.util.module_from_spec(smoke_spec)
smoke_spec.loader.exec_module(smoke)


@pytest.fixture
def lock():
    return json.loads((ROOT / 'config/fingerprint-rpms.lock.json').read_text())


def test_source_pins_match_reviewed_distro_inputs(lock):
    for package, previous, field in (
        (lock['packages'][0], 'elan-diagnostics', 'sources'),
        (lock['packages'][1], 'gnome-fingerprint', 'reviewed_sources'),
    ):
        reviewed = json.loads((ROOT / f'config/{previous}.lock.json').read_text())[field][0]
        assert package['sha256'] == reviewed['package_sha256']
        assert package['url'] == reviewed['package_url']
        assert (ROOT / package['patch']).is_file()


def test_guest_refuses_host_before_build():
    result = subprocess.run([sys.executable, ROOT / 'guest/fingerprint-rpms.py'], text=True, capture_output=True)
    assert result.returncode != 0
    assert 'isolated Fedora builder VM' in result.stderr


def test_smoke_refuses_host_before_install():
    result = subprocess.run([sys.executable, ROOT / 'guest/fingerprint-rpm-smoke.py'], text=True, capture_output=True)
    assert result.returncode != 0
    assert 'isolated Fedora builder VM' in result.stderr


@pytest.mark.parametrize('text,code,expected', [
    ('1..2\nok 1 /first\nok 2 /second\n', 0, True),
    ('1..2\nok 1 /first\nok 2 /second\n', 1, False),
    ('1..2\nok 1 /first\n', 0, False),
    ('1..0\n', 0, False),
    ('1..1\nok 1 /first # SKIP\n', 0, False),
    ('1..1\nok 1 /first # TODO\n', 0, False),
    ('1..1\nok 1 /first\nBail out!\n', 0, False),
    ('1..1\nok 1 /first\nnot ok 2 /second\n', 0, False),
])
def test_smoke_requires_complete_tap_without_skips(text, code, expected):
    assert smoke.tap_passed(text, code) is expected


@pytest.mark.parametrize('index', [0, 1])
def test_spec_changes_only_release_patch_and_explicit_strip(lock, index):
    package = lock['packages'][index]
    text = 'Name: test\nRelease:        %autorelease\nSource0: archive\n\n%prep\n' + package['prep'] + '\n%build\n%meson_build\n'
    result = build.prepare_spec(text, package, lock['release'])
    assert 'Release:        1%{?dist}.apex1\n' in result
    assert result.count('Patch1000:') == 1
    assert package['prep_patched'] in result
    assert '%build\n%meson_build\n' in result
    assert '%check' not in result
    assert '-Ddrivers=' not in result


@pytest.mark.parametrize('mutation', ['release', 'patch', 'prep', 'source'])
def test_changed_spec_layout_is_rejected(lock, mutation):
    package = lock['packages'][0]
    text = 'Release: %autorelease\nSource0: archive\n' + package['prep']
    text = {'release': text.replace('%autorelease', '2'), 'patch': text + '\nPatch1: unknown',
            'prep': text.replace(package['prep'], '%setup'), 'source': text.replace('Source0:', 'Source1:')}[mutation]
    with pytest.raises(ValueError):
        build.prepare_spec(text, package, lock['release'])


@pytest.mark.parametrize('prefix', ['', './'])
def test_cpio_accepts_expected_relative_members(lock, prefix):
    p = lock['packages'][0]
    build.validate_members([prefix + p['name'] + '.spec', prefix + p['archive']], p)


@pytest.mark.parametrize('extra', ['../escape', '/etc/passwd', 'unknown.patch', './libfprint.spec'])
def test_cpio_rejects_unexpected_or_duplicate_members(lock, extra):
    p = lock['packages'][0]
    with pytest.raises(ValueError):
        build.validate_members(['./libfprint.spec', p['archive'], extra], p)


@pytest.mark.parametrize('valid', [True, False])
def test_archive_patch_preflight_catches_application_failure(tmp_path, valid):
    archive = tmp_path / 'source.tar'
    with tarfile.open(archive, 'w') as stream:
        data = b'first\nold\nlast\n'
        member = tarfile.TarInfo('upstream/file.c')
        member.size = len(data)
        stream.addfile(member, io.BytesIO(data))
    patch = tmp_path / 'change.patch'
    patch.write_text('--- a/file.c\n+++ b/file.c\n@@ -1,3 +1,3 @@\n first\n-old\n+new\n last\n'
                     .replace('-old', '-missing' if not valid else '-old'))
    if valid:
        build.validate_patch_archive(archive, patch)
    else:
        with pytest.raises(subprocess.CalledProcessError):
            build.validate_patch_archive(archive, patch)


@pytest.fixture
def report_fixture(tmp_path):
    manifest = {'files': {'config/fingerprint-rpms.lock.json': 'a' * 64,
                         'rpms/patches/libfprint-elan-status-diagnostics.patch': 'b' * 64,
                         'rpms/patches/gnome-fingerprint-retain-claim.patch': 'c' * 64}}
    report = {'status': 'PASS', 'stage': 'rpm-build', 'source_lock_sha256': 'a' * 64,
              'ready_to_install': False, 'hardware': 'NOT TESTED', 'image_integration': 'NOT TESTED',
              'full_gtk_dbus_integration': 'NOT TESTED', 'packages': {}, 'artifacts': {}}
    for name, checksum in [('libfprint', 'b' * 64), ('gnome-control-center', 'c' * 64)]:
        report['packages'][name] = {'status': 'PASS', 'patch_sha256': checksum, 'rpms': {'test.rpm': 'fixture'}}
        path = tmp_path / name / 'mock/test.rpm'
        path.parent.mkdir(parents=True)
        path.write_bytes(b'test artifact')
        report['artifacts'][str(path.relative_to(tmp_path))] = sha256(path)
    repo = tmp_path / 'packages/repodata/repomd.xml'
    repo.parent.mkdir(parents=True)
    repo.write_text('test repository')
    report['artifacts'][str(repo.relative_to(tmp_path))] = sha256(repo)
    return tmp_path, report, manifest


def test_transferred_report_and_artifacts_verified(report_fixture):
    out, report, manifest = report_fixture
    (out / 'results.json').write_text(json.dumps(report))
    assert runner.verify_report(out, manifest)['status'] == 'PASS'


@pytest.mark.parametrize('fault', ['hardware-pass', 'missing-package', 'patch', 'missing-rpm', 'tamper', 'escape', 'symlink'])
def test_incomplete_or_tampered_transfer_rejected(report_fixture, fault):
    out, report, manifest = report_fixture
    if fault == 'hardware-pass':
        report['hardware'] = 'PASS'
    elif fault == 'missing-package':
        del report['packages']['libfprint']
    elif fault == 'patch':
        report['packages']['libfprint']['patch_sha256'] = 'd' * 64
    elif fault == 'missing-rpm':
        del report['artifacts']['libfprint/mock/test.rpm']
    elif fault == 'tamper':
        (out / 'libfprint/mock/test.rpm').write_bytes(b'changed')
    elif fault == 'escape':
        report['artifacts']['../outside'] = 'e' * 64
    elif fault == 'symlink':
        path = out / 'libfprint/mock/test.rpm'
        path.unlink()
        path.symlink_to(out / 'gnome-control-center/mock/test.rpm')
    (out / 'results.json').write_text(json.dumps(report))
    with pytest.raises(Blocked):
        runner.verify_report(out, manifest)
