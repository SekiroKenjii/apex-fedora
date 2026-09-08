import json
import socket
import threading
import pytest
from apexlib.vm import QMP
from apexlib.common import Blocked


@pytest.mark.parametrize('failure', [False, True])
def test_qmp_ignores_events_and_matches_response_ids(tmp_path, failure):
    path = tmp_path / 'qmp.sock'
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(path))
    listener.listen()

    def server():
        client, _ = listener.accept()
        with client, client.makefile('rwb') as stream:
            stream.write(b'{"QMP": {}}\n')
            stream.flush()
            for index in range(2):
                request = json.loads(stream.readline())
                stream.write(b'{"event":"STOP"}\n')
                response = {'id': request['id']}
                if index and failure:
                    response['error'] = {'class': 'GenericError', 'desc': 'fixture'}
                else:
                    response['return'] = {'status': 'running'} if index else {}
                stream.write(json.dumps(response).encode() + b'\n')
                stream.flush()
        listener.close()

    thread = threading.Thread(target=server)
    thread.start()
    client = QMP(path)
    try:
        if failure:
            with pytest.raises(Blocked):
                client.call('query-status')
        else:
            assert client.call('query-status')['status'] == 'running'
    finally:
        client.close()
        thread.join(timeout=2)
    assert not thread.is_alive()
