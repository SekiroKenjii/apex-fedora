"""Transfer reviewed probes to an existing owned live-VM root shell."""
import json
from pathlib import Path
import uuid

from .common import ROOT, atomic_json, sha256
from .serialconsole import SerialConsole

PROBES = {'observe': 'live-probe.py', 'ventoy-observe': 'ventoy-probe.py', 'write-denial': 'live-write-denial.py',
          'usb-write-denial': 'live-usb-probe.py', 'lock-fault': 'live-lock-fault.py'}


def source_for(case):
    filename = PROBES[case]
    source = ''
    if case in {'usb-write-denial', 'lock-fault'}:
        dependency = (ROOT / 'guest/live-write-denial.py').read_text()
        source = ("import types,sys\nm=types.ModuleType('apex_live_write')\n"
                  f"exec(compile({dependency!r},'live-write-denial.py','exec'),m.__dict__)\n"
                  "sys.modules['apex_live_write']=m\n")
    if case == 'lock-fault':
        digest = sha256(ROOT / 'live/rootfs/usr/libexec/apex/live-disk-guard.sh')
        source += f'EXPECTED_GUARD_SHA256={digest!r}\n'
    return source + (ROOT / 'guest' / filename).read_text()


def decode_object(response):
    # Terminal escape sequences can precede JSON. These probes print one object.
    index = response.index(b'{')
    value, _ = json.JSONDecoder().raw_decode(response[index:].decode())
    if not isinstance(value, dict):
        raise ValueError('Probe response is not an object')
    return value


def execute(directory: Path, case: str):
    source = source_for(case)
    serial = SerialConsole(directory)
    try:
        capture, response = serial.execute(source)
        report = decode_object(response)
        destination = Path(serial.info['artifacts_dir']) / f'{case}-{uuid.uuid4().hex}.json'
        atomic_json(destination, {'case': case, 'capture': str(capture), 'result': report})
        return destination
    finally:
        serial.close()
