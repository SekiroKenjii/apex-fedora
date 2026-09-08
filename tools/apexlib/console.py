"""Local QMP display and keyboard access for an owned disposable test VM."""
from pathlib import Path
import time
from .common import Blocked
from .vm import QMP, alive


def character_keys(character):
    plain = {' ': 'spc', '\n': 'ret', '\t': 'tab', '-': 'minus', '=': 'equal',
             '[': 'bracket_left', ']': 'bracket_right', '\\': 'backslash',
             ';': 'semicolon', "'": 'apostrophe', ',': 'comma', '.': 'dot',
             '/': 'slash', '`': 'grave_accent'}
    shifted = dict(zip('!@#$%^&*()', '1234567890')) | {
        '_': 'minus', '+': 'equal', '{': 'bracket_left', '}': 'bracket_right',
        '|': 'backslash', ':': 'semicolon', '"': 'apostrophe', '<': 'comma',
        '>': 'dot', '?': 'slash', '~': 'grave_accent'}
    if len(character) != 1 or not character.isascii():
        raise Blocked('QMP text input requires supported US-layout ASCII')
    if character.isalnum():
        return (['shift'] if character.isupper() else []) + [character.lower()]
    if character in plain:
        return [plain[character]]
    if character in shifted:
        return ['shift', shifted[character]]
    raise Blocked('Unsupported QMP text character')


class Console:
    def __init__(self, directory: Path):
        self.directory = directory
        self.info = alive(directory)
        if not self.info or self.info['role'] != 'test':
            raise Blocked('Console input requires an owned disposable test VM')

    def call(self, command, arguments):
        if alive(self.directory) != self.info:
            raise Blocked('The test VM changed; select its console again')
        connection = QMP(self.directory / 'qmp.sock')
        try:
            return connection.call(command, arguments)
        finally:
            connection.close()

    def keys(self, *codes):
        # send-key queues a timed delay after every press and release. Long input
        # can overflow its bounded queue and lose modifier releases. Send explicit
        # events and leave time for the emulated keyboard to consume each edge.
        def events(down):
            sequence = codes if down else reversed(codes)
            return {'events': [{'type': 'key', 'data': {
                'down': down, 'key': {'type': 'qcode', 'data': code}}} for code in sequence]}

        try:
            self.call('input-send-event', events(True))
            time.sleep(.15)
        finally:
            self.call('input-send-event', events(False))

    def text(self, value):
        if len(value) > 128:
            raise Blocked('Console text is limited to 128 characters; transfer scripts through verified SSH or serial input')
        sequence = [character_keys(character) for character in value]
        # Validate the complete input before sending its first key. Never log passwords.
        for keys in sequence:
            self.keys(*keys)
            time.sleep(.15)

    def screenshot(self, path: Path):
        if not path.resolve().is_relative_to(Path(self.info['artifacts_dir']).resolve()) or path.is_symlink():
            raise Blocked('Console screenshots must be inside the current test evidence directory')
        arguments = {'filename': str(path.resolve())}
        if path.suffix == '.png':
            arguments['format'] = 'png'
        self.call('screendump', arguments)
