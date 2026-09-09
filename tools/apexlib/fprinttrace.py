"""Reduce fprintd D-Bus metadata without retaining usernames or print data."""
import json
from pathlib import Path
import re
import subprocess
import time

SERVICE = 'net.reactivated.Fprint'
INTERFACE = SERVICE + '.Device'
MATCHES = ["path_namespace='/net/reactivated/Fprint'", "sender='net.reactivated.Fprint'",
           "type='signal',interface='org.freedesktop.DBus',member='NameOwnerChanged'"]
METHODS = {'Claim', 'Release', 'EnrollStart', 'EnrollStop', 'VerifyStart', 'VerifyStop'}
STATUSES = {'enroll-stage-passed', 'enroll-completed', 'enroll-failed', 'enroll-data-full',
            'enroll-disconnected', 'enroll-unknown-error', 'enroll-retry-scan',
            'enroll-swipe-too-short', 'enroll-finger-not-centered', 'enroll-remove-and-retry',
            'enroll-duplicate', 'verify-match', 'verify-no-match', 'verify-retry-scan',
            'verify-swipe-too-short', 'verify-finger-not-centered', 'verify-remove-and-retry',
            'verify-disconnected', 'verify-unknown-error'}


def unique(value):
    return isinstance(value, str) and re.fullmatch(r':[0-9]+\.[0-9]+', value) is not None


def client_process(name):
    if not unique(name):
        return {'status': 'UNKNOWN'}
    try:
        result = subprocess.run(['busctl', '--system', '--auto-start=no', '--timeout=1', 'call',
                                 'org.freedesktop.DBus', '/org/freedesktop/DBus',
                                 'org.freedesktop.DBus', 'GetConnectionUnixProcessID', 's', name],
                                capture_output=True, text=True, timeout=2)
        match = re.fullmatch(r'u ([1-9][0-9]*)\s*', result.stdout) if result.returncode == 0 else None
        if match is None:
            return {'status': 'UNKNOWN'}
        pid = int(match[1])
        # Only a process basename. Never read cmdline, environ, or another user's files.
        executable = Path(f'/proc/{pid}/exe').resolve(strict=True).name
        return {'status': 'OBSERVED', 'pid': pid, 'executable': executable}
    except (OSError, subprocess.TimeoutExpired):
        return {'status': 'UNKNOWN'}


class Trace:
    def __init__(self, lookup=None):
        self.lookup = lookup
        self.clients = {}
        self.pending = {}
        self.owners = {}
        self.disconnected = set()
        self.events = []
        self.errors = []

    def feed(self, message):
        if not isinstance(message, dict):
            raise ValueError('Expected one busctl JSON object')
        if 'payload' in message and not isinstance(message['payload'], dict):
            raise ValueError('Malformed bus payload envelope')
        kind = message.get('type')
        sender, destination = message.get('sender'), message.get('destination')
        interface, member, path = message.get('interface'), message.get('member'), message.get('path')
        event = None
        if (kind == 'method_call' and interface == INTERFACE and member in METHODS
                and isinstance(path, str) and re.fullmatch(r'/net/reactivated/Fprint/Device/[0-9]+', path)
                and unique(sender) and (destination == SERVICE or unique(destination))):
            serial = message.get('cookie')
            if type(serial) is not int or serial <= 0:
                raise ValueError('Missing call serial')
            if sender not in self.clients:
                self.clients[sender] = self.lookup(sender) if self.lookup else {'status': 'UNKNOWN'}
            self.pending[(sender, serial)] = {'method': member, 'device': path, 'destination': destination}
            event = {'kind': 'call', 'client': sender, 'serial': serial, 'method': member, 'device': path}
        elif kind in {'method_return', 'error'}:
            serial = message.get('reply_cookie')
            # systemd JSON uses underscores in message type and reply_cookie.
            if not unique(destination) or type(serial) is not int:
                return None
            call = self.pending.get((destination, serial))
            if call is None or not unique(sender):
                return None
            if unique(call['destination']) and sender != call['destination']:
                raise ValueError('Reply sender differs from the called device owner')
            del self.pending[(destination, serial)]
            event = {'kind': 'reply', 'client': destination, 'serial': serial,
                     'method': call['method'], 'device': call['device'], 'outcome': 'OK' if kind == 'method_return' else 'ERROR'}
            if kind == 'error':
                name = message.get('error_name', '')
                event['error'] = name if re.fullmatch(r'net\.reactivated\.Fprint\.Error\.[A-Za-z]+', name) else 'OTHER'
                previous = self.owners.get(call['device'])
                event['last_observed_owner'] = previous or 'UNKNOWN'
                event['caller_was_last_owner'] = previous == destination if previous else None
            elif call['method'] == 'Claim':
                previous = self.owners.get(call['device'])
                event['previous_owner'] = previous or 'UNKNOWN'
                event['after_previous_disconnect'] = previous in self.disconnected if previous else False
                self.owners[call['device']] = destination
            elif call['method'] == 'Release':
                if self.owners.get(call['device']) == destination:
                    self.owners[call['device']] = None
        elif kind == 'signal' and interface == INTERFACE and member in {'EnrollStatus', 'VerifyStatus'}:
            payload = message.get('payload', {})
            data = payload.get('data', [])
            if (not isinstance(path, str) or not re.fullmatch(r'/net/reactivated/Fprint/Device/[0-9]+', path)
                    or payload.get('type') != 'sb' or not isinstance(data, list) or len(data) != 2
                    or type(data[1]) is not bool):
                raise ValueError('Malformed fingerprint status')
            event = {'kind': 'status', 'device': path, 'signal': member,
                     'status': data[0] if isinstance(data[0], str) and data[0] in STATUSES else 'UNKNOWN',
                     'done': data[1]}
        elif (kind == 'signal' and sender == 'org.freedesktop.DBus'
              and interface == 'org.freedesktop.DBus' and member == 'NameOwnerChanged'):
            payload = message.get('payload', {})
            data = payload.get('data', [])
            if payload.get('type') != 'sss' or not isinstance(data, list) or len(data) != 3:
                raise ValueError('Malformed bus ownership change')
            name, old, new = data
            if name in self.clients and old == name and new == '':
                self.disconnected.add(name)
                event = {'kind': 'client-disconnected', 'client': name}
            elif name == SERVICE and all(value == '' or unique(value) for value in (old, new)):
                event = {'kind': 'daemon-owner-changed', 'old': old or None, 'new': new or None}
                # A daemon replacement invalidates all previous ownership knowledge.
                self.owners.clear()
                self.pending.clear()
        if event is not None:
            timestamp = message.get('timestamp-realtime')
            if type(timestamp) is not int or timestamp <= 0:
                raise ValueError('Missing bus timestamp')
            event['bus_realtime_us'] = timestamp
            event['observed_monotonic_ns'] = time.monotonic_ns()
            self.events.append(event)
        return event

    def summary(self):
        return {'scope': 'fprintd ownership observations, not hardware acceptance',
                'initial_ownership': 'UNKNOWN', 'fingerprint_acceptance': 'NOT TESTED',
                'capture_status': 'INCOMPLETE' if self.errors or self.pending or not self.events else 'OBSERVED',
                'errors': self.errors, 'clients': self.clients,
                'last_observed_owners': self.owners, 'disconnected_clients': sorted(self.disconnected),
                'pending_replies': len(self.pending), 'event_count': len(self.events),
                'claim_denials': sum(e.get('error') == SERVICE + '.Error.AlreadyInUse' for e in self.events),
                'successful_releases': sum(e.get('method') == 'Release' and e.get('outcome') == 'OK' for e in self.events),
                'claims_after_disconnect': sum(bool(e.get('after_previous_disconnect')) for e in self.events)}


def parse_line(line):
    if len(line) > 256 * 1024:
        raise ValueError('D-Bus event exceeds the capture limit')
    return json.loads(line)
