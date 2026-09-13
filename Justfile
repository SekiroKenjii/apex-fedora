set shell := ["bash", "-eu", "-o", "pipefail", "-c"]
export PYTHONDONTWRITEBYTECODE := "1"

python := env_var_or_default("APEX_PYTHON", "3.14.4")
apex := "PYTHONPATH=src uv run --no-project --python " + python + " python -m apex.cli.main"

default:
    @just --list

build profile="fedora":
    {{apex}} build image --profile "{{profile}}"

artifact kind build_id:
    {{apex}} build "{{kind}}" --parent "{{build_id}}"

test-disk build_id:
    {{apex}} build qcow2 --parent "{{build_id}}" --test-access

installer-fixtures:
    {{apex}} build fixtures

select-candidate build_id key:
    {{apex}} candidate select --build "{{build_id}}" --key "{{key}}"

doctor:
    {{apex}} doctor

verify-chain:
    {{apex}} evidence verify-chain

hardware-snapshot:
    {{apex}} hardware snapshot

hooks:
    {{apex}} hooks

builder-prepare:
    {{apex}} machine prepare

builder-start:
    {{apex}} machine start --role builder

builder-stop:
    {{apex}} machine stop

builder-status:
    {{apex}} machine status

test-vm disk:
    {{apex}} machine start --role test --disk "{{disk}}"

test-installer disk iso other_disk:
    {{apex}} machine start --role test --disk "{{disk}}" --iso "{{iso}}" --medium installer --extra-disk "{{other_disk}}"

test-installer-diagnostic disk iso other_disk:
    {{apex}} machine start --role test --disk "{{disk}}" --iso "{{iso}}" --medium installer --extra-disk "{{other_disk}}" --serial-console

test-live-hotplug disk iso other_disk:
    {{apex}} machine start --role test --disk "{{disk}}" --iso "{{iso}}" --medium live --extra-disk "{{other_disk}}" --serial-console --usb-bus

test-ventoy disk other_disk usb_image:
    {{apex}} machine start --role test --disk "{{disk}}" --extra-disk "{{other_disk}}" --boot-usb "{{usb_image}}" --usb-bus --serial-console

test-hotplug-usb source:
    {{apex}} machine hotplug-usb --source "{{source}}"

test-power-loss:
    {{apex}} machine power-loss

test-compare-disks run_directory:
    {{apex}} machine compare --run "{{run_directory}}"

test-resume-installed run_directory:
    {{apex}} machine resume --run "{{run_directory}}" --without-iso

test-installer-fault-collect run_directory:
    {{apex}} machine collect --run "{{run_directory}}"

plan-artifact kind:
    {{apex}} plan artifact "{{kind}}"

plan-verify recipe:
    {{apex}} plan verify "{{recipe}}"

plan-upgrade release:
    {{apex}} plan upgrade --release "{{release}}"

readiness:
    {{apex}} readiness

report:
    {{apex}} readiness

readiness-table:
    {{apex}} readiness --table

readiness-table-strict:
    {{apex}} readiness --table --strict

sources:
    {{apex}} sources

trust-verify build_id key:
    {{apex}} trust verify --build "{{build_id}}" --key "{{key}}"

trust-exercise build_id key:
    {{apex}} trust exercise --build "{{build_id}}" --key "{{key}}"

trust-development-key:
    {{apex}} trust development-key

verify-live-protection user:
    {{apex}} verify live-protection --user "{{user}}"

verify-desktop-theme user:
    {{apex}} verify desktop-theme --user "{{user}}"

verify-desktop-render credentials:
    {{apex}} verify desktop-render --credentials "{{credentials}}"

test-fingerprint build_id:
    {{apex}} verify fingerprint-cleanup --build "{{build_id}}"

test-installer-trust:
    {{apex}} verify installer-trust

test-live-check case:
    {{apex}} verify "{{case}}" --serial

test-installer-fault case:
    {{apex}} verify installer-payload --case "{{case}}" --serial

test-installer-wrong-key public_key:
    {{apex}} verify installer-payload --case wrong-key --wrong-key "{{public_key}}" --serial

installer-logs-prepare:
    {{apex}} verify installer-diagnostics --serial

installer-logs-collect run_directory token:
    {{apex}} installer-logs collect --run "{{run_directory}}" --token "{{token}}"

observe-fingerprint:
    bash tools/observe-fingerprint.sh

test-fingerprint-dialog source:
    python3 tools/test-fingerprint-dialog.py "{{source}}"

builder-compact:
    python3 tools/compact-builder.py --replace-verified

builder-finalize compaction_id:
    python3 tools/compact-builder.py --replace-verified --resume "{{compaction_id}}"

build-nvidia build_id:
    python3 tools/apex.py build-nvidia --build "{{build_id}}"

build-fingerprint-rpms:
    python3 tools/build-fingerprint-rpms.py

test-fingerprint-rpms build_id:
    python3 tools/test-fingerprint-rpms.py "{{build_id}}"

test-fingerprint-gtk build_id:
    python3 tools/test-fingerprint-gtk.py "{{build_id}}"

build-fingerprint-image parent_build rpm_build gtk_test:
    python3 tools/build-fingerprint-image.py "{{parent_build}}" "{{rpm_build}}" "{{gtk_test}}"

test-elan-diagnostics source:
    python3 tools/test-elan-diagnostics.py "{{source}}"

ventoy-media live_output ubuntu trusted_key checksums signature keyring:
    python3 tools/apex.py ventoy-media --live-output "{{live_output}}" --ubuntu "{{ubuntu}}" --trusted-key "{{trusted_key}}" --checksums "{{checksums}}" --signature "{{signature}}" --keyring "{{keyring}}"

update-fixtures build_id:
    python3 tools/prepare-update-fixture.py "{{build_id}}"

recovery-disk fixture:
    python3 tools/build-recovery-disk.py "{{fixture}}"

test-update action fixture access:
    python3 tools/update-vm.py "{{action}}" "{{fixture}}" "{{access}}"

test-recovery action fixture access:
    python3 tools/recovery-vm.py "{{action}}" "{{fixture}}" "{{access}}"

test-initramfs-inspect fixture access:
    python3 tools/initramfs-vm.py inspect "{{fixture}}" "{{access}}"

test-initramfs-inject fixture access inspection:
    python3 tools/initramfs-vm.py inject "{{fixture}}" "{{access}}" --inspection "{{inspection}}"

test-initramfs-rescue fixture access:
    python3 tools/initramfs-vm.py verify-rescue "{{fixture}}" "{{access}}"

test:
    uv run --no-project --python {{python}} python tools/check_static.py
    uv run --no-project --python {{python}} --with pytest==9.1.1 pytest

test-integration:
    uv run --no-project --python {{python}} --with pytest==9.1.1 pytest -m integration

runtime-freeze:
    uv run --no-project --python {{python}} python tools/migration/runtime_inventory.py record

runtime-verify:
    uv run --no-project --python {{python}} python tools/migration/runtime_inventory.py verify

golden-freeze scratch:
    PYTHONPATH=tools uv run --no-project --python {{python}} python tools/migration/golden_corpus.py record --scratch "{{scratch}}"

golden scratch:
    PYTHONPATH=tools uv run --no-project --python {{python}} python tools/migration/golden_corpus.py verify --scratch "{{scratch}}"

surface-freeze scratch:
    uv run --no-project --python {{python}} python tools/migration/surface_contract.py freeze --scratch "{{scratch}}"

surface:
    uv run --no-project --python {{python}} python tools/migration/surface_contract.py check

ratchet-freeze:
    uv run --no-project --python {{python}} python tools/migration/lint_ratchet.py freeze

ratchet:
    uv run --no-project --python {{python}} python tools/migration/lint_ratchet.py check

types:
    uv run --no-project --python {{python}} --with mypy==1.18.2 mypy --strict src/apex

pyright:
    uv run --no-project --python {{python}} --with pytest==9.1.1 --with pyright==1.1.407 sh -c 'pyright --pythonpath "$(command -v python)"'

deadcode:
    uv run --no-project --python {{python}} --with vulture==2.14 vulture src/apex tools/migration tests/unit tests/pipelines tests/architecture tests/contract tests/property tests/support tests/integration --min-confidence 80

agent-wheel out:
    uv run --no-project --python {{python}} python tools/migration/agent_wheel.py "{{out}}"

plans-freeze:
    uv run --no-project --python {{python}} python tools/migration/golden_plans.py freeze

plans:
    uv run --no-project --python {{python}} python tools/migration/golden_plans.py check

os-freeze:
    uv run --no-project --python {{python}} python tools/migration/generated_os.py freeze

os:
    uv run --no-project --python {{python}} python tools/migration/generated_os.py check

justfile-freeze:
    uv run --no-project --python {{python}} python tools/migration/generated_justfile.py freeze

justfile:
    uv run --no-project --python {{python}} python tools/migration/generated_justfile.py check

benchmarks:
    uv run --no-project --python {{python}} --with pytest==9.1.1 pytest -q -m benchmark --durations=5

lint:
    uv run --no-project --python {{python}} --with ruff==0.14.5 ruff check --no-cache src tools/migration tests/unit tests/pipelines tests/architecture tests/contract tests/property tests/support

readiness-shadow:
    uv run --no-project --python {{python}} python tools/migration/readiness_shadow.py

guard-shadow:
    uv run --no-project --python {{python}} python tools/migration/guard_shadow.py --self-test

gate:
    just test
    just lint
    just types
    just pyright
    just deadcode
    just plans
    just os
    just justfile
    just runtime-verify
    just readiness-shadow
    just verify-chain
    just readiness-table
    just guard-shadow
    just test-integration
    just surface
    just ratchet
    just benchmarks
    uv run --no-project --python {{python}} --with pytest==9.1.1 pytest -q -m golden
