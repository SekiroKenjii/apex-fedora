"""Build-time checks. These never load a module or open a GPU device."""
import json
from pathlib import Path
import re
import subprocess
import sys


def output(*args):
    return subprocess.check_output(args, text=True).strip()


def check_compiler(config, lock):
    entries = re.findall(r'^CONFIG_CC_VERSION_TEXT="([^"]+)"$', config, re.M)
    actual = output('gcc', '--version').splitlines()[0]
    if entries != [lock['compiler_text']] or actual != lock['compiler_text']:
        raise ValueError('Kernel and build compiler must match the reviewed lock')
    return {'compiler': actual, 'status': 'PASS'}


def check_modules(directory, lock):
    files = sorted(directory.glob('*.ko'))
    expected = set(lock['modules'])
    if {p.stem.replace('-', '_') for p in files} != expected or len(files) != len(expected):
        raise ValueError('Missing or unexpected NVIDIA module')
    modules = {}
    for path in files:
        if path.is_symlink() or not path.is_file():
            raise ValueError('Module must be a regular file')
        fields = {key: output('modinfo', '-F', key, str(path))
                  for key in ('name', 'version', 'vermagic', 'depends', 'firmware', 'signer')}
        name = path.stem.replace('-', '_')
        if (fields['name'] != name or fields['version'] != lock['version']
                or fields['vermagic'].split(' ')[0] != lock['kernel_release']):
            raise ValueError('Module name, driver version or target kernel mismatch')
        dependencies = set(filter(None, fields['depends'].replace('-', '_').split(',')))
        required = {'nvidia_modeset': {'nvidia'}, 'nvidia_drm': {'nvidia_modeset'},
                    'nvidia_uvm': {'nvidia'}, 'nvidia': set()}[name]
        if not required <= dependencies:
            raise ValueError('Missing NVIDIA module dependency')
        modules[name] = fields
    return {'status': 'PASS', 'kernel_release': lock['kernel_release'], 'modules': modules,
            'dependency_resolution_in_image': 'NOT TESTED', 'secure_boot': 'NOT TESTED',
            'initramfs': 'NOT TESTED', 'hardware': 'NOT TESTED'}


if __name__ == '__main__':
    action, path, source = sys.argv[1:]
    lock = json.loads(Path(source).read_text())
    if action == 'compiler':
        result = check_compiler(Path(path).read_text(), lock)
    elif action == 'modules':
        result = check_modules(Path(path), lock)
    else:
        raise SystemExit('Unknown NVIDIA check')
    print(json.dumps(result, indent=2))
