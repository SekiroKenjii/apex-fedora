set shell := ["bash", "-eu", "-o", "pipefail", "-c"]
export PYTHONDONTWRITEBYTECODE := "1"

default:
    @just --list

doctor:
    python3 tools/apex.py doctor

hooks:
    python3 tools/apex.py hooks

sources:
    python3 tools/apex.py sources

builder-prepare:
    python3 tools/apex.py builder prepare

builder-start:
    python3 tools/apex.py builder start

builder-stop:
    python3 tools/apex.py builder stop

builder-status:
    python3 tools/apex.py builder status

build profile="fedora":
    python3 tools/apex.py build {{profile}}

artifact kind build_id:
    python3 tools/apex.py artifact "{{kind}}" --build "{{build_id}}"

test-disk build_id:
    python3 tools/apex.py artifact qcow2 --build "{{build_id}}" --test-access

test:
    python3 tools/check_static.py
    uv run --no-project --with pytest==9.1.1 pytest

test-integration:
    uv run --no-project --with pytest==9.1.1 pytest -m integration

test-vm disk:
    python3 tools/apex.py test-vm "{{disk}}"

test-installer disk iso other_disk:
    python3 tools/apex.py test-vm "{{disk}}" --iso "{{iso}}" --extra-disk "{{other_disk}}"

installer-fixtures:
    python3 tools/apex.py installer-fixtures

installer-logs-prepare:
    python3 tools/apex.py installer-logs prepare

installer-logs-collect run_directory token:
    python3 tools/apex.py installer-logs collect --run "{{run_directory}}" --token "{{token}}"

test-resume-installed run_directory:
    python3 tools/apex.py test-resume "{{run_directory}}" --without-iso

test-compare-disks run_directory:
    python3 tools/apex.py test-compare-disks "{{run_directory}}"

report:
    python3 tools/apex.py report

readiness:
    python3 tools/apex.py readiness
