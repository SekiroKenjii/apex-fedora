set shell := ["bash", "-eu", "-o", "pipefail", "-c"]
export PYTHONDONTWRITEBYTECODE := "1"

default:
    @just --list

doctor:
    python3 tools/apex.py doctor

hardware-snapshot:
    python3 tools/apex.py hardware-snapshot

observe-fingerprint:
    bash tools/observe-fingerprint.sh

test-fingerprint-dialog source:
    python3 tools/test-fingerprint-dialog.py "{{source}}"

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

builder-compact:
    python3 tools/compact-builder.py --replace-verified

builder-finalize compaction_id:
    python3 tools/compact-builder.py --replace-verified --resume "{{compaction_id}}"

build profile="fedora":
    python3 tools/apex.py build {{profile}}

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

artifact kind build_id:
    python3 tools/apex.py artifact "{{kind}}" --build "{{build_id}}"

test-disk build_id:
    python3 tools/apex.py artifact qcow2 --build "{{build_id}}" --test-access

test:
    python3 tools/check_static.py
    uv run --no-project --with pytest==9.1.1 pytest

test-elan-diagnostics source:
    python3 tools/test-elan-diagnostics.py "{{source}}"

test-integration:
    uv run --no-project --with pytest==9.1.1 pytest -m integration

test-vm disk:
    python3 tools/apex.py test-vm "{{disk}}"

test-installer disk iso other_disk:
    python3 tools/apex.py test-vm "{{disk}}" --iso "{{iso}}" --extra-disk "{{other_disk}}"

test-installer-diagnostic disk iso other_disk:
    python3 tools/apex.py test-vm "{{disk}}" --iso "{{iso}}" --extra-disk "{{other_disk}}" --serial-console

test-live-hotplug disk iso other_disk:
    python3 tools/apex.py test-vm "{{disk}}" --iso "{{iso}}" --extra-disk "{{other_disk}}" --serial-console --usb-test-bus

test-ventoy disk other_disk usb_image:
    python3 tools/apex.py test-vm "{{disk}}" --extra-disk "{{other_disk}}" --boot-usb "{{usb_image}}" --serial-console

ventoy-media live_output ubuntu trusted_key checksums signature keyring:
    python3 tools/apex.py ventoy-media --live-output "{{live_output}}" --ubuntu "{{ubuntu}}" --trusted-key "{{trusted_key}}" --checksums "{{checksums}}" --signature "{{signature}}" --keyring "{{keyring}}"

test-hotplug-usb source:
    python3 tools/apex.py test-hotplug-usb "{{source}}"

test-live-check case:
    python3 tools/apex.py test-live-check "{{case}}"

test-installer-fault case:
    python3 tools/apex.py test-installer-fault "{{case}}"

test-installer-wrong-key public_key:
    python3 tools/apex.py test-installer-fault wrong-key --wrong-key "{{public_key}}"

test-installer-fault-collect run_directory:
    python3 tools/apex.py test-installer-fault-collect "{{run_directory}}"

installer-fixtures:
    python3 tools/apex.py installer-fixtures

test-installer-trust:
    python3 tools/apex.py test-installer-trust

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

test-fingerprint build_id:
    python3 tools/apex.py test-fingerprint --build "{{build_id}}"

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

runtime-freeze:
    python3 tools/migration/runtime_inventory.py record

runtime-verify:
    python3 tools/migration/runtime_inventory.py verify

gate:
    just test
    just runtime-verify
