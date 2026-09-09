#!/usr/bin/bash
# Operator-run only. Root is used for the bus monitor, not the Python collector.
set -uo pipefail
if [[ $(id -u) == 0 ]]; then
    echo 'Run this command as your normal desktop user.' >&2
    exit 2
fi
project=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
echo 'For 90 seconds, open fingerprint settings, reproduce the error, then cancel and close Settings.'
echo 'Do not delete fingerprints or complete enrollment during this first capture.'
sudo -- /usr/bin/timeout --signal=INT 90s /usr/bin/busctl --system --json=short \
    --match="path_namespace='/net/reactivated/Fprint'" \
    --match="sender='net.reactivated.Fprint'" \
    --match="type='signal',interface='org.freedesktop.DBus',member='NameOwnerChanged'" monitor \
    | /usr/bin/python3 "$project/tools/fingerprint-observe.py" --seconds 120 --lookup-system-clients
codes=("${PIPESTATUS[@]}")
[[ ${codes[1]} == 0 ]] || exit "${codes[1]}"
case "${codes[0]}" in
    0|124|130) exit 0;;
    *) echo 'The system-bus monitor did not complete normally.' >&2; exit "${codes[0]}";;
esac
