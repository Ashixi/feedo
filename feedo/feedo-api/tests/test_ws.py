import asyncio
import importlib.util
from fastapi.testclient import TestClient


def load_app_module():
    spec = importlib.util.spec_from_file_location(
        "feedo_api_main", "./feedo/feedo-api/main.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_ws_subscribe_and_broadcast():
    appmod = load_app_module()
    app = appmod.app
    manager = appmod.manager

    with TestClient(app) as client:
        ws_a = client.websocket_connect('/ws?wallet_address=alice')
        ws_b = client.websocket_connect('/ws?wallet_address=bob')

        # subscribe both to room 123
        ws_a.send_json({'action': 'subscribe', 'room_id': 123})
        msg_a = ws_a.receive_json()
        assert msg_a.get('action') == 'history'
        assert msg_a.get('room_id') == 123

        ws_b.send_json({'action': 'subscribe', 'room_id': 123})
        msg_b = ws_b.receive_json()
        assert msg_b.get('action') == 'history'
        assert msg_b.get('room_id') == 123

        # broadcast a test payload from server side
        payload = {
            'id': 999,
            'sender_wallet': 'alice',
            'ciphertext': 'AAABBB',
            'nonce': 'IVIVIV',
            'protocol_version': '1.0',
            'kdf_info': {},
            'created_at': '2026-05-23T00:00:00Z',
        }

        # manager.broadcast_room is async
        asyncio.get_event_loop().run_until_complete(manager.broadcast_room(123, payload))

        # both clients should receive the payload
        r_a = ws_a.receive_json()
        r_b = ws_b.receive_json()

        assert r_a.get('id') == 999
        assert r_b.get('id') == 999

        ws_a.close()
        ws_b.close()
