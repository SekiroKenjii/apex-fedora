#!/usr/bin/python3
"""Keep Anaconda's paths and SELinux entry point while adding an early check."""
import ast
import hashlib
import json
from pathlib import Path

GUARD = ('# apex-installer-preflight\n'
         'import subprocess as _apex_subprocess\n'
         '_apex_subprocess.run(["/usr/bin/python3", '
         '"/usr/libexec/apex/installer-preflight.py"], check=True)\n')


def guarded(source):
    if not source.startswith('#!/usr/bin/python3\n') or 'apex-installer-preflight' in source:
        raise ValueError('Unrecognized or already guarded Anaconda entry point')
    if any(isinstance(node, ast.ImportFrom) and node.module == '__future__' for node in ast.parse(source).body):
        raise ValueError('Review Anaconda future imports before inserting its guard')
    first, rest = source.split('\n', 1)
    result = first + '\n' + GUARD + rest
    compile(result, '/usr/bin/anaconda', 'exec')
    return result


if __name__ == '__main__':
    entry = Path('/usr/bin/anaconda')
    if not Path('/apex-installer-source/installer-preflight.py').is_file():
        raise SystemExit('Run only while constructing the installer image')
    original = entry.read_text()
    result = guarded(original)
    entry.write_text(result)
    if Path('/usr/sbin/anaconda').read_text() != result:
        raise RuntimeError('Anaconda has a second unguarded entry point')
    Path('/usr/share/apex/installer-entrypoint.json').write_text(json.dumps({
        'upstream_sha256': hashlib.sha256(original.encode()).hexdigest(),
        'guarded_sha256': hashlib.sha256(result.encode()).hexdigest(),
        'guard': 'signature verification before upstream imports', 'boot_test': 'NOT TESTED'}))
