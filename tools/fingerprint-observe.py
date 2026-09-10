#!/usr/bin/env python3
"""Read filtered busctl JSON from stdin; retain only sanitized lifecycle events."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import select
import sys
import time
import uuid

sys.dont_write_bytecode = True
from apexlib.common import atomic_json, state_dir
from apexlib.fprinttrace import Trace, client_process, parse_line


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=int, default=100)
    parser.add_argument('--lookup-system-clients', action='store_true')
    args = parser.parse_args()
    if not 1 <= args.seconds <= 180:
        parser.error('Capture must last between 1 and 180 seconds')
    if os.geteuid() == 0:
        parser.error('Run this collector as your normal user, after the privileged monitor pipe')
    if sys.stdin.isatty():
        parser.error('Pipe filtered busctl JSON into this collector; see docs/HARDWARE-TRACE.md')
    os.umask(0o077)
    directory = state_dir() / 'fingerprint-observations' / uuid.uuid4().hex
    directory.mkdir(parents=True, mode=0o700)
    trace = Trace(lookup=client_process if args.lookup_system_clients else None)
    started = datetime.now(timezone.utc).isoformat()
    deadline = time.monotonic() + args.seconds
    raw = bytearray()
    limited = False
    print(f'Capture output: {directory}', flush=True)
    try:
        with (directory / 'events.jsonl').open('x') as stream:
            while time.monotonic() < deadline:
                ready, _, _ = select.select([sys.stdin], [], [], max(0, min(1, deadline - time.monotonic())))
                if not ready:
                    continue
                chunk = os.read(sys.stdin.fileno(), 8192)
                if not chunk:
                    break
                raw.extend(chunk)
                while b'\n' in raw:
                    line, _, rest = raw.partition(b'\n')
                    raw = bytearray(rest)
                    if not line.strip():
                        continue
                    try:
                        event = trace.feed(parse_line(line))
                    except (ValueError, TypeError, KeyError):
                        # Error text can contain payload data. Retain only this fixed label.
                        trace.errors.append('Malformed monitor event')
                        if len(trace.errors) >= 20:
                            limited = True
                            break
                        continue
                    if event is not None:
                        stream.write(json.dumps(event) + '\n')
                        stream.flush()
                    if len(trace.events) >= 2000 or time.monotonic() >= deadline:
                        limited = True
                        break
                if limited or len(raw) > 256 * 1024:
                    trace.errors.append('Capture size limit reached')
                    break
    except KeyboardInterrupt:
        trace.errors.append('Collector interrupted')
    if raw.strip():
        trace.errors.append('Partial final monitor event')
    report = trace.summary()
    report.update({'started_at': started, 'kernel': os.uname().release,
                   'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip()})
    atomic_json(directory / 'summary.json', report)
    print(json.dumps(report, indent=2))
    return 0 if report['capture_status'] == 'OBSERVED' else 2


if __name__ == '__main__':
    raise SystemExit(main())
