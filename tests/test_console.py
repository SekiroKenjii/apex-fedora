import pytest
from apexlib import console
from apexlib.common import Blocked


def test_qmp_text_key_mapping():
    assert console.character_keys('A') == ['shift', 'a']
    assert console.character_keys(':') == ['shift', 'semicolon']
    assert console.character_keys('/') == ['slash']
    assert console.character_keys('\n') == ['ret']
    with pytest.raises(Blocked):
        console.character_keys('ế')


@pytest.mark.parametrize('info', [None, {'role': 'builder'}])
def test_console_refuses_host_or_builder(tmp_path, monkeypatch, info):
    monkeypatch.setattr(console, 'alive', lambda _: info)
    with pytest.raises(Blocked):
        console.Console(tmp_path)


def test_text_validates_before_sending_anything(tmp_path, monkeypatch):
    monkeypatch.setattr(console, 'alive', lambda _: {'role': 'test'})
    instance = console.Console(tmp_path)
    calls = []
    monkeypatch.setattr(instance, 'keys', lambda *args: calls.append(args))
    with pytest.raises(Blocked):
        instance.text('valid then invalid: ế')
    assert calls == []


def test_console_refuses_bulk_text_before_any_input(tmp_path, monkeypatch):
    monkeypatch.setattr(console, 'alive', lambda _: {'role': 'test'})
    instance = console.Console(tmp_path)
    calls = []
    monkeypatch.setattr(instance, 'keys', lambda *args: calls.append(args))
    with pytest.raises(Blocked, match='128 characters'):
        instance.text('a' * 129)
    assert not calls


def test_console_refuses_vm_replacement(tmp_path, monkeypatch):
    monkeypatch.setattr(console, 'alive', lambda _: {'role': 'test', 'pid': 1})
    instance = console.Console(tmp_path)
    monkeypatch.setattr(console, 'alive', lambda _: {'role': 'test', 'pid': 2})
    with pytest.raises(Blocked, match='changed'):
        instance.keys('ret')


def test_chord_releases_keys_in_reverse_order(tmp_path, monkeypatch):
    monkeypatch.setattr(console, 'alive', lambda _: {'role': 'test'})
    instance = console.Console(tmp_path)
    calls = []
    monkeypatch.setattr(instance, 'call', lambda name, args: calls.append((name, args)))
    monkeypatch.setattr(console.time, 'sleep', lambda _: None)
    instance.keys('shift', 'a')
    assert [name for name, _ in calls] == ['input-send-event', 'input-send-event']
    assert [[(e['data']['key']['data'], e['data']['down']) for e in args['events']]
            for _, args in calls] == [[('shift', True), ('a', True)],
                                     [('a', False), ('shift', False)]]


def test_chord_releases_even_when_hold_is_interrupted(tmp_path, monkeypatch):
    monkeypatch.setattr(console, 'alive', lambda _: {'role': 'test'})
    instance = console.Console(tmp_path)
    calls = []
    monkeypatch.setattr(instance, 'call', lambda name, args: calls.append(args))
    def interrupted(_):
        raise KeyboardInterrupt
    monkeypatch.setattr(console.time, 'sleep', interrupted)
    with pytest.raises(KeyboardInterrupt):
        instance.keys('ctrl', 'c')
    assert len(calls) == 2
    assert all(not e['data']['down'] for e in calls[-1]['events'])
