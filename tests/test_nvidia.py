import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

from apexlib import nvidia
from apexlib.common import ROOT, Blocked, sha256


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


build = load('nvidia_build', 'guest/nvidia-build.py')
checks = load('nvidia_checks', 'guest/nvidia-check.py')
gpu = load('apex_gpu', 'system_files/usr/libexec/apex/gpu.py')
parity = load('nvidia_parity', 'guest/live-parity.py')


@pytest.fixture
def lock():
    return json.loads((ROOT / 'config/nvidia.lock.json').read_text())


def test_checked_in_lock_and_recipe_agree(lock):
    build.validate_lock(lock)
    recipe = (ROOT / 'rpms/kmod-apex-nvidia-open.spec').read_text()
    assert 'kernel-devel = %{apex_kernel_devel_evr}' in recipe
    assert 'gcc = %{apex_compiler_evr}' in recipe
    assert 'KERNEL_UNAME=%{apex_kernel_release}' in recipe
    assert 'SYSOUT=/usr/src/kernels/%{apex_kernel_release}' in recipe
    assert 'IGNORE_CC_MISMATCH' not in recipe
    assert 'modprobe' not in recipe and '%post' not in recipe
    assert 'make -j2 modules' in recipe


@pytest.mark.parametrize('field,value', [
    ('schema', 2), ('repository', 'https://example.com/'), ('version', 'latest'),
    ('kernel_release', '7.1.13-201.fc44.x86_64'), ('compiler_evr', '16.2.1-2.fc43'),
    ('epoch', '0'), ('compiler_text', 'gcc\nanything'), ('modules', ['nvidia']), ('firmware', []),
])
def test_unreviewed_lock_rejected(lock, field, value):
    lock[field] = value
    with pytest.raises(ValueError):
        build.validate_lock(lock)


@pytest.mark.parametrize('fault', ['mixed-version', 'checksum', 'duplicate', 'dkms', 'key', 'source'])
def test_unreviewed_sources_rejected(lock, fault):
    if fault == 'mixed-version':
        lock['packages'][0]['version'] = '610.43.02'
    elif fault == 'checksum':
        lock['source']['sha256'] = ''
    elif fault == 'duplicate':
        lock['packages'].append(copy.deepcopy(lock['packages'][0]))
    elif fault == 'dkms':
        lock['packages'][0]['name'] = 'kmod-nvidia-open-dkms'
    elif fault == 'key':
        lock['signing_key']['fingerprint'] = '0' * 40
    else:
        lock['source']['url'] = lock['source']['url'].rsplit('/', 1)[0] + '/main'
    with pytest.raises(ValueError):
        build.validate_lock(lock)


def test_guest_build_refuses_host_before_commands():
    result = subprocess.run([sys.executable, ROOT / 'guest/nvidia-build.py'], capture_output=True, text=True)
    assert result.returncode != 0
    assert 'isolated Fedora builder VM' in result.stderr


def test_guest_guard_refuses_non_root_before_io(monkeypatch):
    monkeypatch.setattr(build.os, 'geteuid', lambda: 1000)
    monkeypatch.setattr(build, 'command', lambda *args: pytest.fail('Unexpected command'))
    with pytest.raises(RuntimeError, match='isolated Fedora builder'):
        build.require_builder()


@pytest.mark.parametrize('text', ['payload: digests OK', 'RSA/SHA256 Signature, key ID 1234: NOKEY',
                                 'RSA/SHA256 Signature, key ID 1234: NOT OK',
                                 'RSA/SHA256 Signature: OK\nPayload SHA256 digest: BAD'])
def test_unsigned_untrusted_or_corrupt_rpm_cannot_pass(text):
    with pytest.raises(ValueError, match='signature'):
        build.require_signature(text)


def test_valid_signature_is_not_enough_for_wrong_version(lock, monkeypatch, tmp_path):
    package = lock['packages'][0]
    def response(*args):
        if args[0] == 'rpmkeys':
            assert '--dbpath' in args and tmp_path / 'isolated-db' in args
            return 'Header V4 RSA/SHA256 Signature, key ID 73cd9b30: OK\nPayload SHA256 digest: OK'
        return build.rpm_identity(package).replace('610.57.04', '610.43.02')
    monkeypatch.setattr(build, 'command', response)
    with pytest.raises(ValueError, match='NEVRA'):
        build.verify_vendor(tmp_path / 'input.rpm', package, tmp_path / 'isolated-db')


def test_fetch_rejects_payload_checksum_before_use(tmp_path, monkeypatch):
    path = tmp_path / 'input.rpm'
    def download(args, **kwargs):
        assert '--proto' in args and '--proto-redir' in args
        path.write_bytes(b'corrupt fixture')
    monkeypatch.setattr(build.subprocess, 'run', download)
    with pytest.raises(ValueError, match='checksum'):
        build.fetch('https://example.com/input.rpm', path, '0' * 64)


def test_fetch_does_not_overwrite_existing_file(tmp_path, monkeypatch):
    path = tmp_path / 'input.rpm'
    path.write_bytes(b'keep')
    monkeypatch.setattr(build.subprocess, 'run', lambda *a, **k: pytest.fail('Unexpected download'))
    with pytest.raises(ValueError, match='fresh'):
        build.fetch('https://example.com/input.rpm', path, '0' * 64)
    assert path.read_bytes() == b'keep'


@pytest.mark.parametrize('config_compiler,build_compiler', [(False, True), (True, False), (False, False)])
def test_mismatched_compiler_cannot_be_bypassed(lock, monkeypatch, config_compiler, build_compiler):
    actual = lock['compiler_text'] if build_compiler else 'other gcc'
    monkeypatch.setattr(checks, 'output', lambda *args: actual)
    text = lock['compiler_text'] if config_compiler else 'other kernel compiler'
    with pytest.raises(ValueError, match='compiler'):
        checks.check_compiler(f'CONFIG_CC_VERSION_TEXT="{text}"\n', lock)


@pytest.fixture
def modules(lock, tmp_path, monkeypatch):
    data = {}
    for name in lock['modules']:
        (tmp_path / (name.replace('_', '-') + '.ko')).write_bytes(b'unit fixture, not a module')
        data[name] = {'name': name, 'version': lock['version'], 'vermagic': lock['kernel_release'] + ' SMP',
                      'depends': {'nvidia': '', 'nvidia_modeset': 'nvidia', 'nvidia_drm': 'nvidia_modeset,drm',
                                  'nvidia_uvm': 'nvidia,drm'}[name], 'firmware': '', 'signer': ''}
    monkeypatch.setattr(checks, 'output', lambda *args: data[Path(args[3]).stem.replace('-', '_')][args[2]])
    return tmp_path, data


def test_module_metadata_does_not_attest_boot_or_hardware(lock, modules):
    result = checks.check_modules(modules[0], lock)
    assert result['status'] == 'PASS'
    for case in ('secure_boot', 'initramfs', 'hardware', 'dependency_resolution_in_image'):
        assert result[case] == 'NOT TESTED'


@pytest.mark.parametrize('field,value', [('version', '610.43.02'), ('name', 'nouveau'),
                                       ('vermagic', '6.8.0 SMP'), ('depends', '')])
def test_wrong_module_metadata_rejected(lock, modules, field, value):
    path, data = modules
    data['nvidia_drm'][field] = value
    with pytest.raises(ValueError):
        checks.check_modules(path, lock)


def test_missing_module_rejected(lock, modules):
    (modules[0] / 'nvidia-uvm.ko').unlink()
    with pytest.raises(ValueError, match='Missing'):
        checks.check_modules(modules[0], lock)


def test_live_cannot_drift_from_custom_module_or_userspace():
    for name in ('kmod-apex-nvidia-open', 'nvidia-kmod-common', 'libnvidia-ml'):
        assert parity.compare(f'{name} 1 x86_64\n', f'{name} 2 x86_64\n')['status'] == 'FAIL'


@pytest.fixture
def frozen(tmp_path, lock):
    build_id = '1' * 32
    parent = tmp_path / 'exports' / build_id
    out = parent / 'output'
    out.mkdir(parents=True)
    (parent / 'result.json').write_text(json.dumps({'status': 'PASS', 'kind': 'image'}))
    image = 'sha256:' + 'a' * 64
    manifest = out / 'manifest.json'
    manifest.write_text(json.dumps({'config': {'digest': image}}))
    value = {'image_id': image, 'digest': 'sha256:' + sha256(manifest), 'profile': 'fedora'}
    (out / 'image.json').write_text(json.dumps(value))
    (out / 'kernel-config.txt').write_text('CONFIG_CC_VERSION_TEXT="' + lock['compiler_text'] + '"\n')
    return build_id, value, out


def test_packaging_requires_owned_builder(tmp_path, frozen):
    with pytest.raises(Blocked, match='builder VM'):
        nvidia.execute(tmp_path, frozen[0])
    assert not (tmp_path / 'nvidia-builds').exists()


@pytest.mark.parametrize('fault', ['manifest', 'image', 'profile', 'compiler'])
def test_changed_target_rejected_before_builder(tmp_path, frozen, fault):
    _, value, out = frozen
    if fault == 'manifest':
        (out / 'manifest.json').write_text('{}')
    elif fault == 'compiler':
        (out / 'kernel-config.txt').write_text('CONFIG_CC_VERSION_TEXT="other"\n')
    else:
        value['image_id' if fault == 'image' else 'profile'] = 'unreviewed'
        (out / 'image.json').write_text(json.dumps(value))
    with pytest.raises(Blocked):
        nvidia.execute(tmp_path, frozen[0])


@pytest.mark.parametrize('field,value', [('hardware', 'PASS'), ('image_integration', 'PASS'),
                                       ('ready_to_install', True), ('image_id', 'other'),
                                       ('artifacts', {})])
def test_rpm_only_report_cannot_promote_candidate(tmp_path, field, value):
    out = tmp_path / 'output/nvidia'
    out.mkdir(parents=True)
    report = {'status': 'PASS', 'stage': 'rpm-build', 'image_id': 'frozen', 'source_lock_sha256': 'lock',
              'ready_to_install': False, 'hardware': 'NOT TESTED', 'image_integration': 'NOT TESTED',
              'initramfs': 'NOT TESTED', 'secure_boot': 'NOT TESTED'}
    report[field] = value
    (out / 'results.json').write_text(json.dumps(report))
    with pytest.raises(Blocked):
        nvidia.verify_report(tmp_path, {'image_id': 'frozen'}, 'lock')


@pytest.fixture
def exported_rpms(tmp_path, lock):
    out = tmp_path / 'output/nvidia'
    (out / 'packages').mkdir(parents=True)
    (out / 'sources').mkdir()
    for package in lock['packages']:
        path = out / 'packages' / build.filename(package)
        path.write_bytes(('unit fixture ' + package['name']).encode())
        package['sha256'] = sha256(path)
    (out / 'packages' / f'kmod-apex-nvidia-open-{lock["version"]}-1.fc44.x86_64.rpm').write_bytes(b'unit kmod fixture')
    (out / 'sources/nvidia.lock.json').write_text(json.dumps(lock))
    lock_hash = sha256(out / 'sources/nvidia.lock.json')
    report = {'status': 'PASS', 'stage': 'rpm-build', 'image_id': 'frozen', 'source_lock_sha256': lock_hash,
              'ready_to_install': False, 'hardware': 'NOT TESTED', 'image_integration': 'NOT TESTED',
              'initramfs': 'NOT TESTED', 'secure_boot': 'NOT TESTED', 'kernel_release': lock['kernel_release'],
              'version': lock['version'],
              'artifacts': {str(p.relative_to(out)): sha256(p) for p in out.rglob('*') if p.is_file()}}
    (out / 'results.json').write_text(json.dumps(report))
    return out, report, lock_hash


def test_transferred_rpm_set_is_bound_to_exact_lock(tmp_path, exported_rpms):
    _, _, lock_hash = exported_rpms
    assert nvidia.verify_report(tmp_path, {'image_id': 'frozen'}, lock_hash)['status'] == 'PASS'


@pytest.mark.parametrize('fault', ['changed-bytes', 'missing', 'kernel', 'lock', 'escape', 'symlink'])
def test_transferred_rpm_set_rejects_incomplete_or_changed_output(tmp_path, exported_rpms, fault):
    out, report, lock_hash = exported_rpms
    name = next(n for n in report['artifacts'] if n.startswith('packages/nvidia-driver-'))
    if fault == 'changed-bytes':
        (out / name).write_bytes(b'changed')
    elif fault == 'missing':
        del report['artifacts'][name]
    elif fault == 'kernel':
        report['kernel_release'] = 'other'
    elif fault == 'lock':
        lock_hash = 'wrong'
    elif fault == 'escape':
        report['artifacts']['../escape.rpm'] = '0' * 64
    else:
        original = out / name
        moved = out / 'saved.rpm'
        original.rename(moved)
        original.symlink_to(moved)
    (out / 'results.json').write_text(json.dumps(report))
    with pytest.raises(Blocked):
        nvidia.verify_report(tmp_path, {'image_id': 'frozen'}, lock_hash)


def test_offload_launcher_is_packaged_executable():
    subprocess.run(['bash', '-n', ROOT / 'system_files/usr/bin/apex-gpu'], check=True)
    recipe = (ROOT / 'rpms/apex-config.spec').read_text()
    assert 'chmod 0755 %{buildroot}%{_bindir}/apex-gpu' in recipe
    assert '%{_bindir}/apex-gpu' in recipe.split('%files', 1)[1]


def test_gpu_inventory_is_passive_and_missing_state_is_unknown(tmp_path, monkeypatch):
    device = tmp_path / '0000:01:00.0'
    device.mkdir()
    for name, value in {'vendor': '0x10de', 'class': '0x030200', 'device': '0x25a2'}.items():
        (device / name).write_text(value)
    (device / 'driver').symlink_to('/sys/bus/pci/drivers/nvidia')
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: pytest.fail('Unexpected GPU command'))
    result = gpu.inventory(tmp_path)
    assert len(result) == 1 and result[0]['driver'] == 'nvidia'
    assert result[0]['runtime_status'] is None


@pytest.mark.parametrize('devices', [[], [{'vendor': '0x10de', 'driver': 'nouveau'}],
                                    [{'vendor': '0x10de', 'driver': 'nvidia'}] * 2])
def test_offload_refuses_missing_wrong_or_ambiguous_driver(devices):
    with pytest.raises(ValueError, match='exactly one'):
        gpu.launch_environment(devices, {})


def test_offload_sets_child_environment_without_changing_session():
    previous = {'PATH': '/usr/bin', '__NV_PRIME_RENDER_OFFLOAD': '0', 'USER_SETTING': 'keep'}
    result = gpu.launch_environment([{'vendor': '0x10de', 'driver': 'nvidia'}], previous)
    assert result == {**previous, **gpu.OFFLOAD}
    assert previous['__NV_PRIME_RENDER_OFFLOAD'] == '0'


def test_launcher_preserves_argument_boundaries_and_does_not_invoke_shell(monkeypatch):
    calls = []
    monkeypatch.setattr(gpu, 'inventory', lambda: [{'vendor': '0x10de', 'driver': 'nvidia'}])
    monkeypatch.setattr(gpu.os, 'geteuid', lambda: 1000)
    monkeypatch.setattr(gpu.os, 'execvpe', lambda *args: calls.append(args))
    gpu.main(['run', '--gpu', 'nvidia', '--', '/usr/bin/demo', 'a b', '; echo not-executed'])
    assert calls[0][0] == '/usr/bin/demo'
    assert calls[0][1] == ['/usr/bin/demo', 'a b', '; echo not-executed']
    assert calls[0][2]['__GLX_VENDOR_LIBRARY_NAME'] == 'nvidia'


def test_launcher_refuses_root(monkeypatch):
    monkeypatch.setattr(gpu, 'inventory', lambda: [])
    monkeypatch.setattr(gpu.os, 'geteuid', lambda: 0)
    with pytest.raises(SystemExit) as error:
        gpu.main(['run', '--gpu', 'nvidia', '--', 'demo'])
    assert error.value.code == 2
