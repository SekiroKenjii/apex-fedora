import base64
import os
import socket
import subprocess
import threading

import pytest

from apexlib import serialconsole, vm
from apexlib.common import Blocked


@pytest.mark.parametrize('corrupt', [False, True])
def test_transfer_verifies_bytes_before_execution(corrupt):
    source = 'print("verified-probe-ran")\n' + '# payload test\n' * 400
    token = 'a' * 32
    digest, command = serialconsole.transfer(source, token)
    assert max(map(len, command.splitlines())) < 4096
    if corrupt:
        command = command.replace(base64.encodebytes(source.encode()),
                                  base64.encodebytes(source.replace('probe', 'other').encode()))
    result = subprocess.run(['bash'], input=command, capture_output=True)
    if corrupt:
        assert b'transfer checksum mismatch' in result.stderr
        assert b'verified-other-ran' not in result.stdout
        assert f'APEXDONE:{token}:1'.encode() in result.stdout
    else:
        assert b'verified-probe-ran' in result.stdout
        assert f'APEXDONE:{token}:0'.encode() in result.stdout


@pytest.mark.parametrize('source,token', [('', 'a'*32), ('x'*65537, 'a'*32), ('print(1)', 'invalid')])
def test_invalid_transfer_refused(source, token):
    with pytest.raises(Blocked):
        serialconsole.transfer(source, token)


@pytest.mark.parametrize('info', [None, {'role': 'builder'}, {'role': 'test', 'serial_console': False}])
def test_serial_refuses_other_surfaces(tmp_path, monkeypatch, info):
    monkeypatch.setattr(serialconsole, 'alive', lambda _: info)
    with pytest.raises(Blocked, match='owned test VM'):
        serialconsole.SerialConsole(tmp_path)


def test_serial_refuses_wrong_peer(tmp_path, monkeypatch):
    tmp_path.chmod(0o700)
    path = tmp_path / 'serial.sock'
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(path))
    listener.listen()
    monkeypatch.setattr(serialconsole, 'alive', lambda _: {'role': 'test', 'serial_console': True, 'pid': os.getpid()+1})
    try:
        with pytest.raises(Blocked, match='peer'):
            serialconsole.SerialConsole(tmp_path)
    finally:
        listener.close()


def test_serial_is_private_and_never_attached_to_builder(tmp_path, monkeypatch):
    cfg = vm.config()
    code = tmp_path / 'code.fd'
    code.touch()
    cfg['builder']['firmware_code'] = str(code)
    monkeypatch.setattr(vm, 'config', lambda: cfg)
    for name in ('disk.qcow2', 'test-vars.fd', 'builder-vars.fd'):
        (tmp_path / name).touch()
    # pytest paths can exceed AF_UNIX's limit; verify a short runtime path too.
    import tempfile
    with tempfile.TemporaryDirectory(prefix='apex-serial-test-') as short:
        from pathlib import Path
        root = Path(short)
        for name in ('disk.qcow2', 'test-vars.fd', 'builder-vars.fd'):
            (root / name).touch()
        args = vm.command(root, root/'disk.qcow2', 'test', 4096, 4, serial_console=True)
        assert 'chardev:apex-serial' in args
        assert any('server=on,wait=off,logfile=' in arg for arg in args)
        assert not any('host=' in arg for arg in args)
        with pytest.raises(Blocked, match='test VM'):
            vm.command(root, root/'disk.qcow2', 'builder', 4096, 4, serial_console=True)
        root.chmod(0o755)
        with pytest.raises(Blocked, match='private runtime'):
            vm.command(root, root/'disk.qcow2', 'test', 4096, 4, serial_console=True)


def test_socket_cleanup_preserves_non_socket(tmp_path):
    path = tmp_path / 'serial.sock'
    path.write_text('user file')
    with pytest.raises(Blocked, match='Preserving'):
        vm.clear_serial_socket(tmp_path)
    assert path.read_text() == 'user file'


def test_serial_round_trip_and_exclusive_client(tmp_path, monkeypatch):
    import re
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory(prefix='apex-serial-') as short:
        root = Path(short)
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.bind(str(root / 'serial.sock'))
        listener.listen()
        info = {'role': 'test', 'serial_console': True, 'pid': os.getpid(), 'artifacts_dir': str(root / 'run')}
        monkeypatch.setattr(serialconsole, 'alive', lambda _: info)
        errors = []

        def peer():
            try:
                connection, _ = listener.accept()
                with connection:
                    connection.settimeout(3)
                    data = b''
                    while not (match := re.search(rb'APEXREADY:([a-f0-9]{32})', data)):
                        data += connection.recv(8192)
                    token = match[1]
                    connection.sendall(b'\r\nAPEXREADY:' + token + b'\r\n')
                    data = b''
                    while b'APEXDONE:' not in data:
                        data += connection.recv(8192)
                    assert b'transfer checksum mismatch' in data
                    connection.sendall(b'\r\nverified fixture response\r\nAPEXDONE:' + token + b':0\r\n')
            except BaseException as exc:
                errors.append(exc)

        worker = threading.Thread(target=peer, daemon=True)
        worker.start()
        console = serialconsole.SerialConsole(root)
        try:
            with pytest.raises(BlockingIOError):
                serialconsole.SerialConsole(root)
            capture, response = console.execute('print("fixture")', timeout=3)
            assert (capture / 'result.json').is_file()
            assert b'verified fixture response' in response
            monkeypatch.setattr(serialconsole, 'alive', lambda _: None)
            with pytest.raises(Blocked, match='identity changed'):
                console.send(b'ignored')
        finally:
            console.close()
            listener.close()
            worker.join(timeout=4)
        assert not worker.is_alive()
        assert not errors


def test_socket_cleanup_refuses_symlink(tmp_path):
    target = tmp_path / 'keep'
    target.write_text('preserve')
    (tmp_path / 'serial.sock').symlink_to(target)
    with pytest.raises(Blocked, match='Preserving'):
        vm.clear_serial_socket(tmp_path)
    assert target.read_text() == 'preserve'
