#!/usr/bin/python3
"""Exercise fprintd ownership with upstream virtual storage devices in the VM."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

UPSTREAM_CASES = (
    'FPrintdVirtualDeviceStorageTest.test_claim_from_other_client_is_released_when_vanished',
    'FPrintdVirtualDeviceStorageTest.test_claim_disconnect',
    'FPrintdVirtualDeviceStorageTest.test_enroll_running_disconnect',
    'FPrintdVirtualDeviceStorageTest.test_enroll_done_disconnect',
    'FPrintdVirtualDeviceNoStorageEnrollTests.test_enroll_error_proto',
    'FPrintdUtilsTest.test_enroll_error',
)


def verify_sources(source, lock):
    if set(lock['files']) != {'fprintd.py', 'output_checker.py', 'dbusmock/polkitd.py'}:
        raise ValueError('Unexpected upstream test source inventory')
    for name, checksum in lock['files'].items():
        path = source / name
        if (path.is_symlink() or not path.resolve().is_relative_to(source.resolve())
                or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != checksum):
            raise ValueError('Upstream test source checksum mismatch: ' + name)


def outcome(result):
    if result.errors or result.failures or result.unexpectedSuccesses:
        return 'FAIL'
    if result.skipped or result.expectedFailures or result.testsRun != len(UPSTREAM_CASES) + 2:
        return 'BLOCKED'
    return 'PASS'


def main():
    virtual = subprocess.run(['systemd-detect-virt', '--vm'], capture_output=True, text=True)
    if virtual.returncode or virtual.stdout.strip() not in {'kvm', 'qemu'} or not Path('/etc/apex-builder').is_file():
        raise RuntimeError('Requires the isolated Fedora builder VM')
    if os.geteuid() == 0:
        raise RuntimeError('Run fake device tests as the unprivileged builder user')
    source, output = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
    lock = json.loads(Path('config/fingerprint-tests.lock.json').read_text())
    verify_sources(source, lock)
    # No source images or real templates are imported. Virtual storage uses string IDs.
    os.environ.pop('DBUS_SYSTEM_BUS_ADDRESS', None)
    os.environ.pop('FPRINT_BUILD_DIR', None)
    os.environ.pop('UNDER_JHBUILD', None)
    os.environ['POLKITD_MOCK_PATH'] = str(source / 'dbusmock')
    os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
    sys.path.insert(0, str(source))
    spec = importlib.util.spec_from_file_location('upstream_fprintd', source / 'fprintd.py')
    upstream = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = upstream
    spec.loader.exec_module(upstream)

    class ProtocolCleanup(upstream.FPrintdVirtualStorageDeviceBaseTest):
        def fail_enroll(self, device):
            device.EnrollStart('(s)', 'left-index-finger')
            self.send_error(upstream.FPrint.DeviceError.PROTO)
            self.wait_for_result('enroll-disconnected')

        def test_explicit_cleanup_allows_second_client(self):
            self.device.Claim('(s)', 'testuser')
            self.addCleanup(self.try_release)
            self.fail_enroll(self.device)
            bus, other = self.get_secondary_bus_and_device()
            self.addCleanup(bus.close_sync)
            with self.assertFprintError('AlreadyInUse'):
                other.Claim('(s)', 'testuser')
            self.device.EnrollStop()
            self.device.Release()
            other.Claim('(s)', 'testuser')
            other.Release()

        def test_disconnect_after_protocol_error_allows_claim(self):
            bus, other = self.get_secondary_bus_and_device(claim='testuser')
            self.fail_enroll(other)
            bus.flush_sync()
            bus.close_sync()
            # Match upstream's bounded delay for NameOwnerChanged cleanup.
            upstream.time.sleep(1)
            self.device.Claim('(s)', 'testuser')
            self.device.Release()

    suite = unittest.TestSuite()
    loader = unittest.TestLoader()
    for name in UPSTREAM_CASES:
        suite.addTests(loader.loadTestsFromName(name, upstream))
    suite.addTests(loader.loadTestsFromTestCase(ProtocolCleanup))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    report = {'status': outcome(result), 'tests_run': result.testsRun,
              'upstream_cases': UPSTREAM_CASES, 'source_lock': lock,
              'failures': [(test.id(), error) for test, error in result.failures],
              'errors': [(test.id(), error) for test, error in result.errors],
              'skipped': [(test.id(), reason) for test, reason in result.skipped],
              'hardware_acceptance': 'NOT TESTED',
              'scope': 'packaged daemon/libfprint with a private D-Bus and virtual device'}
    (output / 'results.json').write_text(json.dumps(report, indent=2) + '\n')
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
