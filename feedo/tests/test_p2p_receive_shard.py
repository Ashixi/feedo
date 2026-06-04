import os
import hashlib
import importlib.util
from fastapi.testclient import TestClient


# load app module from feedo-api/main.py
HERE = os.path.dirname(__file__)
MAIN_PATH = os.path.abspath(os.path.join(HERE, '..', 'feedo-api', 'main.py'))
spec = importlib.util.spec_from_file_location('feedo_main', MAIN_PATH)
feedo_main = importlib.util.module_from_spec(spec)
spec.loader.exec_module(feedo_main)
app = getattr(feedo_main, 'app')
client = TestClient(app)


def test_receive_shard_roundtrip(tmp_path):
    # prepare file
    shard_id = 'testshard1'
    data = b'hello shard data'
    checksum = hashlib.sha256(data).hexdigest()
    metadata = {"shard_id": shard_id, "checksum": checksum, "size": len(data), "ts": 123456, "origin": "peer_x"}
    # set shared secret env
    os.environ['FEEDO_P2P_SHARED_SECRET'] = 'secret'
    from feedo_parser.p2p.security import make_hmac
    msg = f"{shard_id}:{checksum}:{len(data)}:{metadata['ts']}:{metadata['origin']}"
    h = make_hmac('secret', msg)

    files = {
        'metadata': (None, __import__('json').dumps(metadata), 'application/json'),
        'file': ('shard', data, 'application/octet-stream')
    }
    headers = {'X-P2P-HMAC': h, 'X-P2P-TS': str(metadata['ts'])}
    resp = client.post('/internal/p2p/receive_shard', files=files, headers=headers)
    assert resp.status_code == 200
    j = resp.json()
    assert j.get('status') == 'ok'
    assert j.get('checksum') == checksum
