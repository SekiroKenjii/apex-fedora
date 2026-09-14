"""fprintd's bus traffic reduced to ownership events, with no name, argument or error body kept.

A Claim, Release, Enroll or Verify call is kept with its serial and its device; the reply
that answers it is matched by caller and serial and kept as OK or ERROR with the error's
name alone; an enrolment or verification status is kept when it is one the daemon
defines; a client that leaves the bus is recorded, and a daemon whose name changes hands
clears every ownership the trace had inferred. Method arguments, user names, error message
bodies and every unrelated message are dropped before anything reaches a file. The capture
is written once under a fresh directory beside the store, bounded in events, in errors and
in bytes, and its summary says OBSERVED only for a capture with events, without errors and
without a call left unanswered.
"""

from __future__ import annotations

import dataclasses
import json
import re
from collections.abc import Callable, Mapping
from pathlib import Path

from apex.config import defaults
from apex.kernel import commands, encoding, errors, safepaths
from apex.ports import clock, portset

SERVICE = "net.reactivated.Fprint"
INTERFACE = f"{SERVICE}.Device"
BUS = "org.freedesktop.DBus"
OWNER_CHANGED = "NameOwnerChanged"
ALREADY_IN_USE = f"{SERVICE}.Error.AlreadyInUse"
DEVICE_PATH = re.compile(r"/net/reactivated/Fprint/Device/[0-9]+")
UNIQUE_NAME = re.compile(r":[0-9]+\.[0-9]+")
ERROR_NAME = re.compile(rf"{re.escape(SERVICE)}\.Error\.[A-Za-z]+")
PROCESS_ANSWER = re.compile(r"u ([1-9][0-9]*)\s*")
METHODS = frozenset({"Claim", "Release", "EnrollStart", "EnrollStop", "VerifyStart", "VerifyStop"})
STATUS_SIGNALS = frozenset({"EnrollStatus", "VerifyStatus"})
STATUSES = frozenset(
    {
        "enroll-stage-passed",
        "enroll-completed",
        "enroll-failed",
        "enroll-data-full",
        "enroll-disconnected",
        "enroll-unknown-error",
        "enroll-retry-scan",
        "enroll-swipe-too-short",
        "enroll-finger-not-centered",
        "enroll-remove-and-retry",
        "enroll-duplicate",
        "verify-match",
        "verify-no-match",
        "verify-retry-scan",
        "verify-swipe-too-short",
        "verify-finger-not-centered",
        "verify-remove-and-retry",
        "verify-disconnected",
        "verify-unknown-error",
    }
)
OBSERVED = "OBSERVED"
INCOMPLETE = "INCOMPLETE"
UNKNOWN = "UNKNOWN"
NOT_TESTED = "NOT TESTED"
OTHER = "OTHER"
SCOPE = "fprintd ownership observations, not hardware acceptance"
MALFORMED = "Malformed monitor event"
SIZE_LIMIT = "Capture size limit reached"
PARTIAL = "Partial final monitor event"
PROCESS_QUERY = commands.Argv.of(
    "busctl",
    "--system",
    "--auto-start=no",
    "--timeout=1",
    "call",
    BUS,
    "/org/freedesktop/DBus",
    BUS,
    "GetConnectionUnixProcessID",
    "s",
)
Lookup = Callable[[str], encoding.Document]


def unique(value: object) -> bool:
    return isinstance(value, str) and UNIQUE_NAME.fullmatch(value) is not None


def client_process(ports: portset.HostPorts, name: str) -> encoding.Document:
    """The process behind a bus name: its number and its program's basename, or unknown."""
    if not unique(name):
        return {"status": UNKNOWN}
    try:
        answered = ports.processes.run(
            PROCESS_QUERY.extended(name),
            deadline=defaults.BUS_QUERY_DEADLINE,
            limit=commands.OutputLimit.default(),
        )
    except errors.PortFailure:
        return {"status": UNKNOWN}
    matched = PROCESS_ANSWER.fullmatch(answered.stdout.decode(errors="replace"))
    if not answered.succeeded or matched is None:
        return {"status": UNKNOWN}
    pid = int(matched[1])
    try:
        program = ports.files.resolve(safepaths.SafePath(Path(f"/proc/{pid}/exe")))
    except errors.PortFailure:
        return {"status": UNKNOWN}
    return {"status": OBSERVED, "pid": pid, "executable": program.path.name}


@dataclasses.dataclass(frozen=True, slots=True)
class Pending:
    method: str
    device: str
    destination: str


class Trace:
    """The ownership state inferred so far, fed one bus message at a time."""

    def __init__(self, ticks: clock.ClockPort, lookup: Lookup | None = None) -> None:
        self._ticks = ticks
        self._lookup = lookup
        self.clients: dict[str, encoding.JsonValue] = {}
        self.pending: dict[tuple[str, int], Pending] = {}
        self.owners: dict[str, str | None] = {}
        self.disconnected: set[str] = set()
        self.events: list[dict[str, encoding.JsonValue]] = []
        self.errors: list[str] = []

    def feed(self, message: object) -> dict[str, encoding.JsonValue] | None:
        """The event one message yields, or nothing; a malformed message is a ValueError."""
        if not isinstance(message, Mapping):
            raise ValueError("expected one bus message object")
        if "payload" in message and not isinstance(message["payload"], Mapping):
            raise ValueError("malformed bus payload envelope")
        kind = message.get("type")
        event = None
        if kind == "method_call":
            event = self._call(message)
        elif kind in ("method_return", "error"):
            event = self._reply(message, str(kind))
        elif kind == "signal":
            event = self._signal(message)
        if event is None:
            return None
        return self._stamped(message, event)

    def summary(self) -> encoding.Document:
        complete = not self.errors and not self.pending and bool(self.events)
        return {
            "scope": SCOPE,
            "initial_ownership": UNKNOWN,
            "fingerprint_acceptance": NOT_TESTED,
            "capture_status": OBSERVED if complete else INCOMPLETE,
            "errors": list(self.errors),
            "clients": dict(self.clients),
            "last_observed_owners": dict(self.owners),
            "disconnected_clients": sorted(self.disconnected),
            "pending_replies": len(self.pending),
            "event_count": len(self.events),
            "claim_denials": sum(item.get("error") == ALREADY_IN_USE for item in self.events),
            "successful_releases": sum(
                item.get("method") == "Release" and item.get("outcome") == "OK"
                for item in self.events
            ),
            "claims_after_disconnect": sum(
                bool(item.get("after_previous_disconnect")) for item in self.events
            ),
        }

    def _call(self, message: Mapping[str, object]) -> dict[str, encoding.JsonValue] | None:
        member, path = message.get("member"), message.get("path")
        sender, destination = message.get("sender"), message.get("destination")
        if message.get("interface") != INTERFACE or member not in METHODS:
            return None
        if not isinstance(path, str) or DEVICE_PATH.fullmatch(path) is None:
            return None
        if not unique(sender) or not (destination == SERVICE or unique(destination)):
            return None
        serial = message.get("cookie")
        if type(serial) is not int or serial <= 0:
            raise ValueError("missing call serial")
        client, method = str(sender), str(member)
        if client not in self.clients:
            self.clients[client] = (
                self._lookup(client) if self._lookup is not None else {"status": UNKNOWN}
            )
        self.pending[(client, serial)] = Pending(method, path, str(destination))
        return {
            "kind": "call",
            "client": client,
            "serial": serial,
            "method": method,
            "device": path,
        }

    def _reply(
        self, message: Mapping[str, object], kind: str
    ) -> dict[str, encoding.JsonValue] | None:
        serial, destination = message.get("reply_cookie"), message.get("destination")
        sender = message.get("sender")
        if not unique(destination) or type(serial) is not int:
            return None
        call = self.pending.get((str(destination), serial))
        if call is None or not unique(sender):
            return None
        if unique(call.destination) and sender != call.destination:
            raise ValueError("reply sender differs from the called device owner")
        del self.pending[(str(destination), serial)]
        event: dict[str, encoding.JsonValue] = {
            "kind": "reply",
            "client": str(destination),
            "serial": serial,
            "method": call.method,
            "device": call.device,
            "outcome": "OK" if kind == "method_return" else "ERROR",
        }
        if kind == "error":
            self._note_error(event, call, str(destination), message.get("error_name"))
        elif call.method == "Claim":
            self._note_claim(event, call, str(destination))
        elif call.method == "Release" and self.owners.get(call.device) == destination:
            self.owners[call.device] = None
        return event

    def _note_error(
        self, event: dict[str, encoding.JsonValue], call: Pending, client: str, name: object
    ) -> None:
        named = isinstance(name, str) and ERROR_NAME.fullmatch(name) is not None
        event["error"] = str(name) if named else OTHER
        previous = self.owners.get(call.device)
        event["last_observed_owner"] = previous or UNKNOWN
        event["caller_was_last_owner"] = previous == client if previous else None

    def _note_claim(self, event: dict[str, encoding.JsonValue], call: Pending, client: str) -> None:
        previous = self.owners.get(call.device)
        event["previous_owner"] = previous or UNKNOWN
        event["after_previous_disconnect"] = previous in self.disconnected if previous else False
        self.owners[call.device] = client

    def _signal(self, message: Mapping[str, object]) -> dict[str, encoding.JsonValue] | None:
        interface, member = message.get("interface"), message.get("member")
        if interface == INTERFACE and member in STATUS_SIGNALS:
            return self._status(message, str(member))
        if message.get("sender") == BUS and interface == BUS and member == OWNER_CHANGED:
            return self._owner_change(message)
        return None

    def _status(self, message: Mapping[str, object], member: str) -> dict[str, encoding.JsonValue]:
        path = message.get("path")
        payload = message.get("payload")
        data = payload.get("data", []) if isinstance(payload, Mapping) else []
        shaped = isinstance(payload, Mapping) and payload.get("type") == "sb"
        if not isinstance(path, str) or DEVICE_PATH.fullmatch(path) is None or not shaped:
            raise ValueError("malformed fingerprint status")
        if not isinstance(data, list) or len(data) != 2 or type(data[1]) is not bool:
            raise ValueError("malformed fingerprint status")
        status = data[0] if isinstance(data[0], str) and data[0] in STATUSES else UNKNOWN
        return {
            "kind": "status",
            "device": path,
            "signal": member,
            "status": status,
            "done": data[1],
        }

    def _owner_change(self, message: Mapping[str, object]) -> dict[str, encoding.JsonValue] | None:
        payload = message.get("payload")
        data = payload.get("data", []) if isinstance(payload, Mapping) else []
        shaped = isinstance(payload, Mapping) and payload.get("type") == "sss"
        if not shaped or not isinstance(data, list) or len(data) != 3:
            raise ValueError("malformed bus ownership change")
        name, old, new = (str(item) for item in data)
        if name in self.clients and old == name and new == "":
            self.disconnected.add(name)
            return {"kind": "client-disconnected", "client": name}
        if name == SERVICE and all(value == "" or unique(value) for value in (old, new)):
            self.owners.clear()
            self.pending.clear()
            return {"kind": "daemon-owner-changed", "old": old or None, "new": new or None}
        return None

    def _stamped(
        self, message: Mapping[str, object], event: dict[str, encoding.JsonValue]
    ) -> dict[str, encoding.JsonValue]:
        timestamp = message.get("timestamp-realtime")
        if type(timestamp) is not int or timestamp <= 0:
            raise ValueError("missing bus timestamp")
        event["bus_realtime_us"] = timestamp
        event["observed_monotonic_ns"] = int(self._ticks.now().seconds * 1_000_000_000)
        self.events.append(event)
        return event


def parse_line(line: bytes) -> object:
    if len(line) > defaults.TRACE_LINE_LIMIT.value:
        raise ValueError("bus event exceeds the capture limit")
    return json.loads(line)


@dataclasses.dataclass(frozen=True, slots=True)
class Captured:
    directory: safepaths.SafePath
    summary: encoding.Document

    @property
    def observed(self) -> bool:
        return self.summary.get("capture_status") == OBSERVED


def _consume(trace: Trace, stream: bytes) -> list[bytes]:
    kept: list[bytes] = []
    consumed = 0
    for line in stream.split(b"\n"):
        consumed += len(line) + 1
        if not line.strip():
            continue
        if consumed > defaults.TRACE_RAW_LIMIT.value:
            trace.errors.append(SIZE_LIMIT)
            return kept
        try:
            event = trace.feed(parse_line(line))
        except (ValueError, TypeError, KeyError):
            trace.errors.append(MALFORMED)
            if len(trace.errors) >= defaults.TRACE_ERROR_LIMIT:
                return kept
            continue
        if event is not None:
            kept.append(encoding.canonical(event))
        if len(trace.events) >= defaults.TRACE_EVENT_LIMIT:
            trace.errors.append(SIZE_LIMIT)
            return kept
    return kept


def capture(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot, stream: bytes, *, lookup_clients: bool
) -> Captured:
    """Reduce one monitor transcript to its events and a summary, written beside the store."""
    started = ports.clock.stamp().rendered
    directory = root.child(
        f"{defaults.FINGERPRINT_OBSERVATIONS_DIRECTORY}/{ports.identities.token()}"
    )
    lookup = (lambda name: client_process(ports, name)) if lookup_clients else None
    trace = Trace(ports.clock, lookup)
    events = _consume(trace, stream)
    if stream and not stream.endswith(b"\n") and stream.rsplit(b"\n", 1)[-1].strip():
        trace.errors.append(PARTIAL)
    ports.files.write_atomic(
        directory / defaults.TRACE_EVENTS_NAME,
        b"".join(line + b"\n" for line in events),
        mode=defaults.RECORD_MODE,
    )
    summary: encoding.Document = {
        **trace.summary(),
        "started_at": started,
        "kernel": _read(ports, defaults.KERNEL_RELEASE),
        "boot_id": _read(ports, defaults.BOOT_ID),
    }
    ports.files.write_atomic(
        directory / defaults.TRACE_SUMMARY_NAME,
        encoding.canonical(summary) + b"\n",
        mode=defaults.RECORD_MODE,
    )
    return Captured(directory=directory, summary=summary)


def _read(ports: portset.HostPorts, path: str) -> str:
    return (
        ports.files.read_bytes(safepaths.SafePath(Path(path)), limit=defaults.DOCUMENT_LIMIT.value)
        .decode(errors="replace")
        .strip()
    )
