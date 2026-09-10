"""Checksum-checked Python transfer to an owned test VM's existing rescue shell."""
import base64
import fcntl
import hashlib
import os
from pathlib import Path
import re
import shlex
import socket
import stat
import struct
import time
import uuid

from .common import Blocked, atomic_json
from .vm import alive


def transfer(source, token):
    data = source.encode('utf-8')
    if not data or len(data) > 65536 or not re.fullmatch('[a-f0-9]{32}', token):
        raise Blocked('Use 1 to 65536 bytes of Python and a fresh transfer token')
    digest = hashlib.sha256(data).hexdigest()
    bootstrap = ('import base64,hashlib,sys;'
                 'd=base64.b64decode(b"".join(sys.stdin.buffer.read().split()),validate=True);'
                 f'assert hashlib.sha256(d).hexdigest()=="{digest}","transfer checksum mismatch";'
                 'exec(compile(d,"<apex-verified-serial>","exec"),{"__name__":"__main__"})')
    delimiter = 'APEXEOF_' + token
    encoded = base64.encodebytes(data).decode()
    command = f'python3 -c {shlex.quote(bootstrap)} <<\'{delimiter}\'\n{encoded}{delimiter}\n'
    command += f'printf \'\\nAPEXDONE:{token}:%s\\n\' "$?"\n'
    return digest, command.encode()


class SerialConsole:
    def __init__(self, directory: Path):
        self.directory = directory
        self.info = alive(directory)
        if not self.info or self.info['role'] != 'test' or not self.info.get('serial_console'):
            raise Blocked('Serial input requires an owned test VM launched with --serial-console')
        if directory.stat().st_mode & 0o077:
            raise Blocked('Serial input requires private runtime storage')
        path = directory / 'serial.sock'
        if path.is_symlink() or not stat.S_ISSOCK(path.lstat().st_mode):
            raise Blocked('Expected a local Unix serial socket')
        self.lock = (directory / 'serial-console.lock').open('a')
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.sock.settimeout(5)
            self.sock.connect(str(path))
            pid, uid, _ = struct.unpack('3i', self.sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
            if (pid, uid) != (self.info['pid'], os.getuid()):
                raise Blocked('Serial socket peer is not the owned QEMU process')
        except BaseException:
            self.close()
            raise

    def close(self):
        self.sock.close()
        self.lock.close()

    def send(self, data):
        if alive(self.directory) != self.info:
            raise Blocked('VM identity changed during serial transfer')
        self.sock.sendall(data)

    def until(self, pattern, timeout=45):
        if not 0 < timeout <= 45:
            raise Blocked('Serial waits must be between zero and 45 seconds')
        deadline = time.monotonic() + timeout
        data = b''
        while time.monotonic() < deadline:
            self.sock.settimeout(min(1, max(.01, deadline - time.monotonic())))
            try:
                chunk = self.sock.recv(8192)
            except TimeoutError:
                continue
            if not chunk:
                raise Blocked('Guest closed the serial channel')
            data += chunk
            if len(data) > 2 * 1024 * 1024:
                raise Blocked('Serial response exceeds 2 MiB')
            if re.search(pattern, data):
                return data
        raise Blocked('Serial response timed out; inspect the retained QEMU serial log')

    def execute(self, source, *, timeout=45):
        token = uuid.uuid4().hex
        digest, command = transfer(source, token)
        capture = Path(self.info['artifacts_dir']) / 'serial-captures' / token
        capture.mkdir(parents=True, mode=0o700)
        atomic_json(capture / 'request.json', {'source_sha256': digest, 'vm_pid': self.info['pid'], 'token': token})
        # Authenticate through the existing rescue session, never alter guest PAM.
        self.send(f'\nstty -echo; test "$(id -u)" = 0 && printf \'\\nAPEXREADY:{token}\\n\'\n'.encode())
        self.until(rb'\r?\nAPEXREADY:' + token.encode() + rb'\r?\n')
        self.sock.settimeout(30)
        self.send(command)
        response = self.until(rb'\r?\nAPEXDONE:' + token.encode() + rb':\d+\r?\n', timeout)
        code = int(re.search(rb'\r?\nAPEXDONE:' + token.encode() + rb':(\d+)\r?\n', response)[1])
        # Runtime evidence is private; never publish an unreviewed guest transcript.
        (capture / 'response.log').write_bytes(response)
        atomic_json(capture / 'result.json', {'returncode': code, 'source_sha256': digest,
                                            'response_sha256': hashlib.sha256(response).hexdigest()})
        if code:
            raise Blocked(f'Guest script returned {code}; inspect {capture}')
        return capture, response
