from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import sys

sys.dont_write_bytecode = True
from apexlib import evidence, gitguard, sources, vm
from apexlib.common import ROOT, Blocked, config, run, state_dir


def boot(parser: argparse.ArgumentParser) -> None:
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("doctor", "hooks", "sources", "report", "readiness", "trust-development-key", "test-power-loss", 'installer-fixtures', 'test-installer-trust', 'hardware-snapshot'):
        sub.add_parser(name)

    builder = sub.add_parser("builder")
    builder.add_argument("action", choices=["prepare", "start", "stop", "status", "ssh"])

    hook = sub.add_parser("git-hook")
    hook.add_argument("kind", choices=["pre-commit", "commit-msg", "pre-push"])
    hook.add_argument("arguments", nargs="*")

    build = sub.add_parser("build")
    build.add_argument("profile", choices=["fedora", "cachyos"], default="fedora", nargs="?")

    artifact = sub.add_parser("artifact")
    artifact.add_argument("kind", choices=["qcow2", "installer", "live"])
    artifact.add_argument("--build", required=True, dest="build_id")
    artifact.add_argument("--test-access", action="store_true", help="Add a private test account and SSH boot argument to QCOW2 only")

    fingerprint = sub.add_parser('test-fingerprint')
    fingerprint.add_argument('--build', required=True, dest='build_id')

    test = sub.add_parser("test-vm")
    test.add_argument("disk", type=Path)
    test.add_argument("--iso", type=Path)
    test.add_argument("--guest-ssh", action="store_true")
    test.add_argument('--serial-console', action='store_true', help='Enable a private Unix serial socket for disposable guest diagnostics')
    test.add_argument('--extra-disk', action='append', type=Path, default=[])

    resume = sub.add_parser('test-resume')
    resume.add_argument('run_directory', type=Path)
    resume.add_argument('--without-iso', action='store_true')

    compare = sub.add_parser('test-compare-disks')
    compare.add_argument('run_directory', type=Path)

    fault = sub.add_parser('test-installer-fault')
    from apexlib.installerfault import CASES
    fault.add_argument('case', choices=CASES)
    fault.add_argument('--wrong-key', type=Path)
    collect_fault = sub.add_parser('test-installer-fault-collect')
    collect_fault.add_argument('run_directory', type=Path)

    logs = sub.add_parser('installer-logs')
    logs.add_argument('action', choices=['prepare', 'collect'])
    logs.add_argument('--run', dest='run_directory', type=Path)
    logs.add_argument('--token')

    verify = sub.add_parser("verify-artifact")
    verify.add_argument("directory", type=Path)
    verify.add_argument("--trusted-key", required=True, type=Path)

    signature_test = sub.add_parser('test-artifact')
    signature_test.add_argument('directory', type=Path)
    signature_test.add_argument('--trusted-key', required=True, type=Path)

    hda = sub.add_parser("decode-coefficient")
    for operand in ("nid", "verb", "parameter"):
        hda.add_argument(operand, type=lambda value: int(value, 0))

    select = sub.add_parser('select-candidate')
    select.add_argument('--build', required=True, dest='build_id')
    select.add_argument('--trusted-key', required=True, type=Path)

    record = sub.add_parser('record')
    record.add_argument('check')
    record.add_argument('status', choices=sorted(evidence.STATUSES))
    record.add_argument('--environment', required=True, choices=['build', 'vm', 'physical', 'operator'])
    record.add_argument('--description', required=True)
    record.add_argument('--proof', type=Path, action='append', default=[])
    record.add_argument('--reason', default='')

    args = parser.parse_args()
    if args.command == "git-hook":
        if args.kind == "pre-commit":
            gitguard.inspect_tree(ROOT)
        elif args.kind == "commit-msg":
            gitguard.validate_subject(Path(args.arguments[0]).read_text())
        else:
            gitguard.inspect_outgoing(ROOT, sys.stdin.read())
        return
    if args.command == "hooks":
        gitguard.install()
        print("Local Git hooks installed")
        return
    if args.command == "decode-coefficient":
        from apexlib.hda import decode_coefficient
        print(json.dumps(decode_coefficient(args.nid, args.verb, args.parameter), indent=2))
        return
    state = state_dir()
    if args.command == 'trust-development-key':
        from apexlib.signatures import trust_builder
        print(json.dumps(trust_builder(state), indent=2))
    elif args.command == 'hardware-snapshot':
        from apexlib.hardware import collect
        print(collect(state))
    elif args.command == 'installer-fixtures':
        from apexlib.pipeline import installer_fixtures
        print(installer_fixtures(state))
    elif args.command == 'test-installer-trust':
        from apexlib.pipeline import installer_trust
        print(installer_trust(state))
    elif args.command == 'test-fingerprint':
        from apexlib.pipeline import fingerprint_tests
        print(fingerprint_tests(state, args.build_id))
    elif args.command == "doctor":
        cfg = config()["builder"]
        tools = {name: shutil.which(name) for name in ("python3", "qemu-system-x86_64", "qemu-img", "ssh", "ssh-keygen", "curl", "uv")}
        result = {"tools": tools, "kvm": os.access("/dev/kvm", os.R_OK | os.W_OK), "available_memory_mib": vm.available_mib(), "required_memory_mib": cfg["memory_mib"] + cfg["reserve_mib"], "free_gib": shutil.disk_usage(state).free // 1024**3, "required_free_gib": cfg["minimum_free_gib"], "state": str(state), "vm": vm.alive(state), "firmware": all(Path(cfg[x]).is_file() for x in ("firmware_code", "firmware_vars"))}
        print(json.dumps(result, indent=2))
        if not all(tools.values()) or not result["firmware"]:
            raise Blocked("Missing host tools or OVMF firmware")
        vm.resources(state, cfg["memory_mib"], cfg["reserve_mib"], cfg["minimum_free_gib"])
    elif args.command == "sources":
        print(json.dumps(sources.acquire(state), indent=2))
    elif args.command == "builder":
        if args.action == "ssh":
            run(vm.ssh_args(state) + ["true"])
        elif args.action == "status":
            print(json.dumps(vm.alive(state), indent=2))
        else:
            result = getattr(vm, args.action)(state)
            if result:
                print(json.dumps(result, indent=2))
    elif args.command in {"build", "artifact"}:
        from apexlib.pipeline import execute
        execute(state, getattr(args, "profile", "fedora"), getattr(args, "kind", "image"), getattr(args, "build_id", None), test_access=getattr(args, "test_access", False))
    elif args.command == "test-vm":
        print(json.dumps(vm.start(state, disk=args.disk, iso=args.iso, guest_ssh=args.guest_ssh, extra_disks=tuple(args.extra_disk), serial_console=args.serial_console), indent=2))
        print("VM launched. This does not record a successful boot or desktop test.")
    elif args.command == 'test-resume':
        print(json.dumps(vm.resume_test(state, args.run_directory, without_iso=args.without_iso), indent=2))
    elif args.command == 'test-compare-disks':
        print(json.dumps(vm.compare_disks(state, args.run_directory), indent=2))
    elif args.command == 'test-installer-fault':
        from apexlib.installerfault import execute
        print(json.dumps(execute(state, args.case, args.wrong_key), indent=2))
    elif args.command == 'test-installer-fault-collect':
        from apexlib.installerfault import collect
        print(json.dumps(collect(state, args.run_directory), indent=2))
    elif args.command == 'installer-logs':
        from apexlib import installerlogs
        if args.action == 'prepare':
            if args.run_directory or args.token:
                raise Blocked('Prepare uses only the currently running installer VM')
            result = installerlogs.prepare(state)
        else:
            if not args.run_directory or not args.token:
                raise Blocked('Collect needs the run directory and token from prepare')
            result = installerlogs.collect(state, args.run_directory, args.token)
        print(json.dumps(result, indent=2))
        if args.action == 'collect' and not result['required_logs_complete']:
            raise Blocked('Capture retained, but required installer logs are missing, truncated or invalid')
    elif args.command == 'test-power-loss':
        vm.power_loss(state)
        print('Disposable test VM terminated for fault injection; no host power action was taken')
    elif args.command == "verify-artifact":
        from apexlib.signatures import verify
        print(json.dumps(verify(args.directory, args.trusted_key), indent=2))
    elif args.command == 'test-artifact':
        from apexlib.signatures import exercise
        print(exercise(args.directory, args.trusted_key, state))
    elif args.command == 'select-candidate':
        import re
        from apexlib.signatures import verify
        from apexlib.common import atomic_json, regular_file
        if not re.fullmatch(r'[a-f0-9]{32}', args.build_id):
            raise Blocked('Invalid build ID')
        export = state / 'exports' / args.build_id
        result = json.loads(regular_file(export / 'result.json', within=state).read_text())
        if result['status'] != 'PASS' or result['kind'] != 'image':
            raise Blocked('Select a completed image build')
        signed = verify(export / 'output', args.trusted_key)
        evidence.select(state, {'digest': signed['digest'], 'build_id': args.build_id, 'verification': signed})
        print('Candidate selected for testing, not approved for installation')
    elif args.command == 'record':
        result = evidence.record(state, args.check, args.status, args.environment, args.description, args.proof, args.reason)
        print(json.dumps({'recorded': args.check, 'ready_to_install': result['ready_to_install']}, indent=2))
    else:
        result = evidence.report(state)
        print(json.dumps(result, indent=2))
        if args.command == "readiness" and not result["ready_to_install"]:
            raise Blocked("Installation is blocked; inspect readiness.json for missing evidence")
