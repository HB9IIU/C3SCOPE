import json
import threading
import unittest
from concurrent.futures import Future
from types import SimpleNamespace
from unittest.mock import Mock, patch

from simple_websocket import Client
from werkzeug.serving import make_server
import app as backend
from firmware_setup import fingerprint
from serial_policy import validate_remote_write
from test_backend import FakeSerial


class ReleaseSecurityTests(unittest.TestCase):
    def test_lan_command_policy_accepts_receiver_operations(self):
        for command in (b'\n', b'\nSYNC 123456789\n', b'INFO\n', b'CAPS\n',
                        b'SPECINFO?\n', b'GAIN MANUAL 0\n', b'GAIN HARDWARE\n',
                        b'FREQ 2406\n', b'BANDWIDTH 0\n', b'SPEC 0 4 1 0 6 2048 1\n',
                        b'CAP20 16380 1\n', b'LPF AUTO\n', b'RELEASE\n'):
            validate_remote_write(command)

    def test_lan_rejects_bootloader_packets_gpio_actuation_and_partial_commands(self):
        for data in (b'\xc0\x00\x08\x24\x00\xc0', b'INFO\n\x00\n', b'GPIO 10 1\n',
                     b'ERASE\n', b'PA 1\n', b'FREQ 2406', b'INFO\nERASE\n'):
            with self.assertRaises(ValueError):
                validate_remote_write(data)

    def test_untrusted_host_is_rejected_before_firmware_api(self):
        with backend.app.test_client() as client:
            with patch.object(backend.installer, 'prepare') as prepare:
                response = client.post('/api/setup/prepare', base_url='http://rebind.example',
                                       headers={'Origin': 'http://rebind.example'}, json={'device': 'COM1'})
                self.assertEqual(response.status_code, 400)
                prepare.assert_not_called()

    def test_non_object_json_is_rejected_without_server_error(self):
        with backend.app.test_client() as client:
            for data in ([], 'unexpected', None):
                response = client.post('/api/setup/prepare', data=json.dumps(data),
                                       content_type='application/json', headers={'Origin': 'http://localhost'})
                self.assertEqual(response.status_code, 400)

    def test_remote_bootloader_bytes_never_reach_serial(self):
        port = FakeSerial()
        original = (backend.receiver.port, backend.receiver.info, backend.receiver.leased)
        backend.receiver.port = port
        backend.receiver.info = SimpleNamespace(device='COM_TEST', vid=0x303a, pid=0x1001)
        backend.receiver.leased = False
        server = make_server('127.0.0.1', 0, backend.app, threaded=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        client = None
        try:
            with patch.object(backend, 'local_browser', return_value=False):
                client = Client.connect(f'ws://127.0.0.1:{server.server_port}/serial',
                                        headers={'Origin': 'http://127.0.0.1'})
                self.assertTrue(json.loads(client.receive(timeout=2))['ready'])
                client.send(b'INFO\n')
                client.send(json.dumps({'op': 'open', 'baudRate': 2000000, 'id': 1}))
                self.assertEqual(json.loads(client.receive(timeout=2)), {'ack': 1})
                client.send(b'\xc0\x00\x08\x24\x00\xc0')
                with self.assertRaises(Exception):
                    client.receive(timeout=2)
                self.assertEqual(port.written, [b'INFO\n'])
        finally:
            if client:
                try:
                    client.close()
                except Exception:
                    pass
            server.shutdown(); server.server_close(); thread.join(timeout=2)
            backend.receiver.port, backend.receiver.info, backend.receiver.leased = original

    def test_old_probe_cannot_identify_replacement_board_on_reused_com_port(self):
        receiver = backend.Receiver()
        old = SimpleNamespace(device='COM_TEST', vid=0x303a, pid=0x1001, serial_number='old')
        new = SimpleNamespace(device='COM_TEST', vid=0x303a, pid=0x1001, serial_number='new')
        stale_port = FakeSerial()
        future = Future()
        future.set_result(((stale_port, 'C3SDR 6 burst 16380'), {'fingerprint': fingerprint(old)}))
        receiver.probes[old.device] = future
        receiver.executor = Mock()
        with patch.object(backend.list_ports, 'comports', return_value=[new]):
            receiver.scan_concurrently()
        self.assertTrue(stale_port.closed)
        self.assertIsNone(receiver.port)
        receiver.executor.submit.assert_called_once()


if __name__ == '__main__':
    unittest.main()
