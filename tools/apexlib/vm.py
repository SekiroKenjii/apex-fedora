from __future__ import annotations

import contextlib
import fcntl
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import time
import uuid

from .common import ROOT, Blocked, atomic_json, config, output, regular_file, run
from .sources import download


def available_mib() -> int:
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) // 1024
    raise Blocked("Cannot read available host memory")


def resources(directory: Path, memory: int, reserve: int, free_gib: int):
    if available_mib() < memory + reserve:
        raise Blocked(f"VM needs {memory + reserve} MiB available including host reserve; found {available_mib()} MiB")
    if shutil.disk_usage(directory).free < free_gib * 1024**3:
        raise Blocked(f"Need {free_gib} GiB free in the runtime directory")
    if not os.access("/dev/kvm", os.R_OK | os.W_OK):
        raise Blocked("This user cannot access /dev/kvm")


def alive(directory: Path) -> dict | None:
    state = directory / "vm.json"
    if not state.exists():
        return None
    info = json.loads(state.read_text())
    proc = Path(f"/proc/{info['pid']}/cmdline")
    if not proc.exists():
        return None
    args = proc.read_bytes().split(b"\0")
    if not any(args):
        return None
    if str(directory / "qmp.sock").encode() not in b"\0".join(args):
        raise Blocked("Saved VM PID belongs to another process; refusing to control it")
    return info


@contextlib.contextmanager
def exclusive(directory: Path):
    with (directory / "vm.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def validate_disk(path: Path, directory: Path):
    visited = set()
    while True:
        path = regular_file(path, within=directory)
        if path in visited:
            raise Blocked("Cycle in virtual disk backing chain")
        visited.add(path)
        info = json.loads(output(["qemu-img", "info", "--output=json", path]))
        if info["format"] != "qcow2":
            raise Blocked("Only QCOW2 disks are accepted")
        backing = info.get("backing-filename")
        if not backing:
            return
        path = path.parent / backing


def command(directory: Path, disk: Path, role: str, memory: int, cpus: int, seed: Path | None = None, port: int | None = None, artifacts_dir: Path | None = None, extra_disks: tuple[Path, ...] = ()) -> list[str]:
    cfg = config()["builder"]
    artifacts_dir = artifacts_dir or directory
    if not artifacts_dir.resolve().is_relative_to(directory.resolve()):
        raise Blocked('VM evidence must stay inside runtime storage')
    regular_file(disk, within=directory)
    regular_file(Path(cfg["firmware_code"]))
    regular_file(artifacts_dir / f"{role}-vars.fd", within=directory)
    if extra_disks and role != 'test':
        raise Blocked('Additional disks are restricted to test VMs')
    if len(extra_disks) > 2 or len({disk.resolve(), *(p.resolve() for p in extra_disks)}) != 1 + len(extra_disks):
        raise Blocked('Use at most two distinct additional test disks')
    for extra in extra_disks:
        regular_file(extra, within=directory)
    args = ["qemu-system-x86_64", "-name", f"apex-{role}", "-machine", "q35,accel=kvm", "-cpu", "host", "-smp", str(cpus), "-m", str(memory), "-display", "none", "-vga", "none", "-device", "virtio-vga", "-monitor", "none", "-qmp", f"unix:{directory}/qmp.sock,server=on,wait=off", "-serial", f"file:{artifacts_dir}/{role}-serial.log", "-drive", f"if=pflash,format=raw,readonly=on,file={cfg['firmware_code']}", "-drive", f"if=pflash,format=raw,file={artifacts_dir}/{role}-vars.fd", "-drive", f"if=virtio,format=qcow2,file={disk}"]
    if seed:
        regular_file(seed, within=directory)
        args += ["-drive", f"file={seed},format=raw,media=cdrom,readonly=on"]
    for index, extra in enumerate(extra_disks, 1):
        args += ['-drive', f'if=none,id=apex-other-{index},format=qcow2,file={extra}',
                 '-device', f'virtio-blk-pci,drive=apex-other-{index},serial=apex-other-{index}']
    if port:
        restricted = ",restrict=on" if role == 'test' else ''
        args += ["-netdev", f"user,id=net0{restricted},hostfwd=tcp:127.0.0.1:{port}-:22", "-device", "virtio-net-pci,netdev=net0"]
    else:
        args += ["-nic", "none"]
    # Commas are QEMU option separators, even when no shell is used.
    paths = [directory, artifacts_dir, disk, Path(cfg['firmware_code']), *extra_disks] + ([seed] if seed else [])
    if any(c in str(path) for path in paths for c in (",", "\n", "\r")):
        raise Blocked("Runtime paths cannot contain QEMU option separators")
    return args


class QMP:
    def __init__(self, path: Path):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(10)
        self.sock.connect(str(path))
        self.stream = self.sock.makefile("rwb")
        greeting = json.loads(self.stream.readline())
        if "QMP" not in greeting:
            raise Blocked("Unexpected QMP greeting")
        self.call("qmp_capabilities")

    def call(self, name: str, arguments: dict | None = None):
        ident = uuid.uuid4().hex
        request = {"execute": name, "id": ident}
        if arguments:
            request["arguments"] = arguments
        self.stream.write(json.dumps(request).encode() + b"\n")
        self.stream.flush()
        while True:
            line = self.stream.readline()
            if not line:
                raise Blocked("VM closed its QMP connection")
            response = json.loads(line)
            if response.get("id") == ident:
                if "error" in response:
                    raise Blocked(str(response["error"]))
                return response["return"]

    def close(self):
        self.stream.close()
        self.sock.close()


def prepare(directory: Path):
    if alive(directory):
        raise Blocked("Stop the current VM before preparing builder storage")
    cfg = config()["builder"]
    base = directory / "builder-base.qcow2"
    download(cfg["url"], base, cfg["sha256"])
    # The base itself must not reference another host file.
    info = json.loads(output(["qemu-img", "info", "--output=json", base]))
    if info["format"] != "qcow2" or info.get("backing-filename"):
        raise Blocked("Builder base must be a standalone QCOW2")
    disk = directory / "builder.qcow2"
    if not disk.exists():
        run(["qemu-img", "create", "-f", "qcow2", "-F", "qcow2", "-b", base, disk, f"{cfg['disk_gib']}G"])
    key = directory / "builder_ed25519"
    if not key.exists():
        run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "apex-local-builder", "-f", key])
    seed = directory / "seed.iso"
    if not seed.exists():
        userdata = {
            "users": [{"name": "builder", "groups": ["wheel"], "sudo": ["ALL=(ALL) NOPASSWD:ALL"], "shell": "/bin/bash", "lock_passwd": True, "ssh_authorized_keys": [(directory / "builder_ed25519.pub").read_text().strip()]}],
            "ssh_pwauth": False,
            "disable_root": True,
            "write_files": [{"path": "/etc/apex-builder", "permissions": "0600", "content": "apex-isolated-builder-v1\n"}],
            "runcmd": [["systemctl", "disable", "--now", "packagekit.service"]],
        }
        (directory / "user-data").write_text("#cloud-config\n" + json.dumps(userdata))
        (directory / "meta-data").write_text(json.dumps({"instance-id": "apex-builder-" + uuid.uuid4().hex, "local-hostname": "apex-builder"}))
        if not shutil.which("uv"):
            raise Blocked("Install uv or create a NoCloud seed ISO from the generated user-data and meta-data")
        run(["uv", "run", "--no-project", "--with", "pycdlib==1.14.0", "python", ROOT / "tools/make_seed.py", directory])
    varfile = directory / "builder-vars.fd"
    if not varfile.exists():
        shutil.copyfile(cfg["firmware_vars"], varfile)


def start(directory: Path, *, disk: Path | None = None, iso: Path | None = None, guest_ssh: bool = False, extra_disks: tuple[Path, ...] = ()):
    with exclusive(directory):
        if alive(directory):
            raise Blocked("Only one Apex VM may run at a time")
        cfg = config()["builder"]
        role = "test" if disk or iso else "builder"
        if iso and not disk:
            raise Blocked('An ISO test requires a file-backed target disk')
        if extra_disks and (role != 'test' or len(extra_disks) > 2):
            raise Blocked('Additional disks require a test VM with at most two extra disks')
        memory = 4096 if disk else cfg["memory_mib"]
        resources(directory, memory, cfg["reserve_mib"], 12 if disk else cfg["minimum_free_gib"])
        disk = disk or directory / "builder.qcow2"
        validate_disk(disk, directory)
        for extra in extra_disks:
            validate_disk(extra, directory)
        if len({disk.resolve(), *(p.resolve() for p in extra_disks)}) != 1 + len(extra_disks):
            raise Blocked('Test disks must be distinct')
        source_disk = disk
        source_extra_disks = extra_disks
        artifacts_dir = directory
        if role == "test":
            artifacts_dir = directory / 'vm-runs' / uuid.uuid4().hex
            artifacts_dir.mkdir(parents=True, mode=0o700)
            overlay = artifacts_dir / 'disk.qcow2'
            run(["qemu-img", "create", "-f", "qcow2", "-F", "qcow2", "-b", disk, overlay])
            disk = overlay
            extra_overlays = []
            for index, extra in enumerate(extra_disks, 1):
                overlay = artifacts_dir / f'other-{index}.qcow2'
                run(['qemu-img', 'create', '-f', 'qcow2', '-F', 'qcow2', '-b', extra, overlay])
                extra_overlays.append(overlay)
            extra_disks = tuple(extra_overlays)
            shutil.copyfile(cfg["firmware_vars"], artifacts_dir / "test-vars.fd")
            shutil.copyfile(cfg["firmware_vars"], artifacts_dir / "initial-vars.fd")
        qmp = directory / "qmp.sock"
        if qmp.exists():
            qmp.unlink()
        args = command(directory, disk, role, memory, cfg["cpus"], directory / "seed.iso" if role == "builder" else iso, cfg["ssh_port"] if role == "builder" else (22245 if guest_ssh else None), artifacts_dir, extra_disks)
        if iso:
            args += ['-boot', 'order=d']
        with (artifacts_dir / f"{role}-qemu.log").open("ab") as log:
            proc = subprocess.Popen(args, stdout=log, stderr=log, stdin=subprocess.DEVNULL, start_new_session=True)
        info = {"pid": proc.pid, "role": role, "disk": str(disk), "source_disk": str(source_disk), "artifacts_dir": str(artifacts_dir), "command": args,
                'iso': str(iso) if iso else None, 'guest_ssh': guest_ssh,
                'extra_disks': [str(p) for p in extra_disks], 'source_extra_disks': [str(p) for p in source_extra_disks]}
        atomic_json(directory / "vm.json", info)
        if role == 'test':
            atomic_json(artifacts_dir / 'vm.json', info)
        time.sleep(1)
        if proc.poll() is not None:
            raise Blocked(f"QEMU exited; inspect {role}-qemu.log")
        return alive(directory)


def resume_test(directory: Path, artifacts_dir: Path, *, without_iso: bool = False):
    """Reboot the same disposable disks and VARS after a stopped test or injected crash."""
    with exclusive(directory):
        if alive(directory):
            raise Blocked('Stop the current VM before resuming a test')
        root = directory / 'vm-runs'
        saved = json.loads(regular_file(artifacts_dir / 'vm.json', within=root).read_text())
        if saved['role'] != 'test' or Path(saved['artifacts_dir']).resolve() != artifacts_dir.resolve():
            raise Blocked('Only an existing disposable test run may be resumed')
        disk = regular_file(Path(saved['disk']), within=artifacts_dir)
        extras = tuple(regular_file(Path(p), within=artifacts_dir) for p in saved.get('extra_disks', []))
        for path in (disk, *extras):
            validate_disk(path, directory)
        cfg = config()['builder']
        resources(directory, 4096, cfg['reserve_mib'], 12)
        iso = None if without_iso or not saved.get('iso') else Path(saved['iso'])
        args = command(directory, disk, 'test', 4096, cfg['cpus'], iso,
                       22245 if saved.get('guest_ssh') else None, artifacts_dir, extras)
        if iso:
            args += ['-boot', 'order=d']
        qmp = directory / 'qmp.sock'
        if qmp.exists():
            qmp.unlink()
        stamp = uuid.uuid4().hex
        atomic_json(artifacts_dir / f'before-resume-{stamp}.json', saved)
        # Preserve prior boot evidence before QEMU opens its serial output file.
        serial = artifacts_dir / 'test-serial.log'
        if serial.exists():
            shutil.copyfile(serial, artifacts_dir / f'before-resume-{stamp}-serial.log')
        shutil.copyfile(artifacts_dir / 'test-vars.fd', artifacts_dir / f'before-resume-{stamp}-vars.fd')
        with (artifacts_dir / 'test-qemu.log').open('ab') as log:
            proc = subprocess.Popen(args, stdout=log, stderr=log, stdin=subprocess.DEVNULL, start_new_session=True)
        info = saved | {'pid': proc.pid, 'command': args, 'iso': str(iso) if iso else None}
        atomic_json(artifacts_dir / 'vm.json', info)
        atomic_json(directory / 'vm.json', info)
        time.sleep(1)
        if proc.poll() is not None:
            raise Blocked('Resumed QEMU exited; inspect the retained test-qemu.log')
        return alive(directory)


def compare_disks(directory: Path, artifacts_dir: Path):
    """Compare complete guest-visible contents while every Apex VM is stopped."""
    with exclusive(directory):
        if alive(directory):
            raise Blocked('Stop the VM before comparing virtual disks')
        saved = json.loads(regular_file(artifacts_dir / 'vm.json', within=directory / 'vm-runs').read_text())
        if saved['role'] != 'test' or Path(saved['artifacts_dir']).resolve() != artifacts_dir.resolve():
            raise Blocked('Disk comparison requires a disposable test run')
        sources = [saved['source_disk'], *saved.get('source_extra_disks', [])]
        overlays = [saved['disk'], *saved.get('extra_disks', [])]
        if len(sources) != len(overlays):
            raise Blocked('Incomplete disk comparison metadata')
        observations = []
        for source, overlay in zip(sources, overlays):
            source = regular_file(Path(source), within=directory)
            overlay = regular_file(Path(overlay), within=artifacts_dir)
            validate_disk(source, directory)
            validate_disk(overlay, directory)
            result = subprocess.run(['qemu-img', 'compare', '-f', 'qcow2', '-F', 'qcow2', source, overlay], text=True, capture_output=True)
            if result.returncode not in (0, 1):
                raise Blocked(f'Virtual disk comparison failed: {result.stderr}')
            observations.append({'source': str(source), 'overlay': str(overlay),
                                 'unchanged': result.returncode == 0, 'output': result.stdout.strip()})
        record = {'method': 'qemu-img compare: complete guest-visible disk contents', 'disks': observations}
        atomic_json(artifacts_dir / f'disk-comparison-{uuid.uuid4().hex}.json', record)
        return record


def stop(directory: Path):
    with exclusive(directory):
        if not alive(directory):
            return
        connection = QMP(directory / "qmp.sock")
        try:
            connection.call("system_powerdown")
        finally:
            connection.close()
        for _ in range(45):
            if not alive(directory):
                return
            time.sleep(1)
        raise Blocked("Guest did not shut down within 45 seconds; it remains running")


def power_loss(directory: Path):
    """Crash only an owned disposable test VM, using a PID handle to avoid PID reuse."""
    with exclusive(directory):
        info = alive(directory)
        if not info or info['role'] != 'test':
            raise Blocked('Power-loss injection is restricted to disposable test VMs')
        capture = Path(info['artifacts_dir'])
        if not capture.resolve().is_relative_to((directory / 'vm-runs').resolve()):
            raise Blocked('Test VM has no isolated evidence directory')
        fd = os.pidfd_open(info['pid'])
        try:
            if alive(directory) != info:
                raise Blocked('VM identity changed before fault injection')
            atomic_json(capture / 'power-loss.json', {'fault': 'guest-power-loss', 'pid': info['pid'], 'host_rebooted': False, 'simulates_physical_storage_power_loss': False})
            signal.pidfd_send_signal(fd, signal.SIGKILL)
        finally:
            os.close(fd)


def ssh_args(directory: Path) -> list[str]:
    info = alive(directory)
    if not info or info["role"] != "builder":
        raise Blocked("Start the isolated builder VM first")
    return ["ssh", "-i", str(directory / "builder_ed25519"), "-p", str(config()["builder"]["ssh_port"]), "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", "-o", "StrictHostKeyChecking=accept-new", "-o", f"UserKnownHostsFile={directory}/known_hosts", "builder@127.0.0.1"]
