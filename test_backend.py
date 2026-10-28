import json
import threading
import os
import signal
import subprocess
import sys
from concurrent.futures import Future, ThreadPoolExecutor
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from simple_websocket import Client
from werkzeug.serving import make_server
import app as backend


class FakeSerial:
    def __init__(self, **kwargs):
        self.baudrate = kwargs.get('baudrate', 2000000)
        self.lines = []
        self.written = []
        self.closed = False
        self.in_waiting = 0

    def open(self):
        pass

    def write(self, data):
        self.written.append(data)
        if b'SYNC ' in data:
            self.lines.append(data.strip() + b'\n')
        if data == b'INFO\n':
            self.lines.append(b'C3SDR 6 burst 2048\n')

    def readline(self):
        return self.lines.pop(0) if self.lines else b''

    def read(self, count):
        return b''

    def close(self):
        self.closed = True


class ImmediateExecutor:
    """Runs probes at once so scan_concurrently can be stepped deterministically."""
    def __init__(self, results):
        self.results = results

    def submit(self, fn, info):
        future = Future()
        future.set_result(self.results.pop(0))
        return future


class SetupReportStabilityTests(unittest.TestCase):
    def board(self):
        return SimpleNamespace(device='COM12', vid=0x303a, pid=0x1001, serial_number='80:F1',
                               location=None, hwid='USB VID:PID=303A:1001 SER=80:F1')

    def good_report(self, board):
        return {'device': board.device, 'fingerprint': backend.fingerprint(board), 'setup_eligible': True,
                'firmware_kind': 'unknown', 'state': 'unrecognized', 'message': 'blank board'}

    def receiver(self, results):
        receiver = backend.Receiver()
        receiver.executor = ImmediateExecutor(results)
        return receiver

    def step(self, receiver, ports):
        with patch.object(backend.list_ports, 'comports', return_value=ports):
            receiver.scan_concurrently()

    def test_board_that_drops_off_usb_briefly_is_not_forgotten(self):
        board = self.board()
        receiver = self.receiver([(None, self.good_report(board))])
        self.step(receiver, [board])   # submit probe
        self.step(receiver, [board])   # collect it
        self.assertEqual(backend.probe_status['state'], 'unrecognized')
        self.step(receiver, [])        # the ESP32 resets and re-enumerates
        self.assertIn('COM12', receiver.reports)
        self.assertEqual(backend.probe_status['state'], 'unrecognized')
        self.step(receiver, [board])
        self.assertIn('COM12', receiver.reports)

    def test_board_is_forgotten_after_the_grace_period(self):
        board = self.board()
        receiver = self.receiver([(None, self.good_report(board))])
        self.step(receiver, [board])
        self.step(receiver, [board])
        start = backend.time.monotonic()
        with patch.object(backend.time, 'monotonic', return_value=start):
            self.step(receiver, [])
        with patch.object(backend.time, 'monotonic', return_value=start + backend.REPORT_GRACE + 1):
            self.step(receiver, [])
        self.assertNotIn('COM12', receiver.reports)
        self.assertEqual(backend.probe_status['state'], 'searching')

    def test_failed_reprobe_does_not_erase_a_good_result(self):
        board = self.board()
        receiver = self.receiver([(None, self.good_report(board)), (None, {})])
        self.step(receiver, [board])
        self.step(receiver, [board])
        receiver.next_probe['COM12'] = 0   # the next probe runs now, and cannot open the port
        self.step(receiver, [board])
        self.step(receiver, [board])
        self.assertEqual(receiver.reports['COM12'].get('state'), 'unrecognized')
        self.assertEqual(backend.probe_status['state'], 'unrecognized')

    def test_a_different_device_on_the_same_com_name_replaces_the_report(self):
        board = self.board()
        receiver = self.receiver([(None, self.good_report(board)), (None, {})])
        self.step(receiver, [board])
        self.step(receiver, [board])
        other = SimpleNamespace(device='COM12', vid=0x303a, pid=0x1001, serial_number='AA:BB',
                                location=None, hwid='USB VID:PID=303A:1001 SER=AA:BB')
        self.step(receiver, [other])
        self.assertNotEqual(receiver.reports.get('COM12', {}).get('fingerprint'), backend.fingerprint(board))


class BackendTests(unittest.TestCase):
    def test_hotplug_receiver_is_found_while_another_port_is_still_probing(self):
        receiver = backend.Receiver()
        slow = SimpleNamespace(device='COM15', vid=0x10c4, pid=60000)
        arriving = SimpleNamespace(device='COM12', vid=0x303a, pid=0x1001)
        release = threading.Event()
        started = threading.Event()
        fast_done = threading.Event()
        def probe(info):
            if info.device == 'COM15':
                started.set()
                release.wait(3)
                return None, {}
            fast_done.set()
            return (FakeSerial(), 'C3SDR 6 burst 16380'), {}
        with ThreadPoolExecutor(max_workers=2) as executor:
            receiver.executor = executor
            try:
                with patch.object(receiver, 'probe', side_effect=probe):
                    with patch.object(backend.list_ports, 'comports', return_value=[slow]):
                        receiver.scan_once()
                    self.assertTrue(started.wait(1))
                    with patch.object(backend.list_ports, 'comports', return_value=[slow, arriving]):
                        receiver.scan_once()
                        self.assertTrue(fast_done.wait(1))
                        receiver.probes['COM12'].result(timeout=1)
                        receiver.scan_once()
                    self.assertEqual(receiver.info.device, 'COM12')
                    self.assertFalse(receiver.probes['COM15'].done())
            finally:
                release.set()
                receiver.close()

    @unittest.skipUnless(os.name == 'nt', 'Windows console shutdown regression')
    def test_console_shutdown_with_open_websocket(self):
        script = (
            "import app; from test_backend import FakeSerial; from types import SimpleNamespace; "
            "app.receiver.port=FakeSerial(); "
            "app.receiver.info=SimpleNamespace(device='COM99',vid=12346,pid=4097); "
            "app.receiver.scan=lambda: app.receiver.stop.wait(); app.main(port=0, open_browser=False, single_instance=False)"
        )
        process = subprocess.Popen([sys.executable, '-u', '-c', script],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
        client = None
        try:
            startup = process.stdout.readline()
            url = startup.split('http://', 1)[1].split(' ', 1)[0]
            client = Client.connect(f'ws://{url}/serial', headers={'Origin': 'http://127.0.0.1'})
            self.assertTrue(json.loads(client.receive(timeout=2))['ready'])
            process.send_signal(signal.CTRL_BREAK_EVENT)
            output, errors = process.communicate(timeout=5)
            self.assertEqual(process.returncode, 0, errors)
            self.assertIn('Serial port released.', output)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()
            if client:
                try:
                    client.close()
                except Exception:
                    pass

    def test_busy_unidentified_port_does_not_replace_waiting_status(self):
        info = SimpleNamespace(device='COM15', vid=0x303a, pid=0x1001)
        for state in ('searching', 'incompatible'):
            expected = {'state': state, 'message': 'Existing device information'}
            with patch.dict(backend.probe_status, expected, clear=True):
                with patch.object(FakeSerial, 'open', side_effect=backend.serial.SerialException('Access denied')):
                    with patch.object(backend.serial, 'Serial', FakeSerial):
                        self.assertIsNone(backend.detect(info))
                self.assertEqual(backend.probe_status, expected)

    def test_busy_port_does_not_prevent_finding_receiver_on_next_port(self):
        receiver = backend.Receiver()
        busy = SimpleNamespace(device='COM15', vid=0x303a, pid=0x1001)
        available = SimpleNamespace(device='COM16', vid=0x303a, pid=0x1001)
        with patch.object(backend.list_ports, 'comports', return_value=[busy, available]):
            with patch.object(backend, 'detect', side_effect=[None, (FakeSerial(), 'C3SDR 6 burst 2048')]):
                receiver.scan_once()
        self.assertEqual(receiver.info.device, 'COM16')
        receiver.close()

    def test_scanner_survives_hotplug_enumeration_error(self):
        receiver = backend.Receiver()
        calls = []
        def step():
            calls.append(1)
            if len(calls) == 1:
                raise OSError('USB changing')
            receiver.stop.set()
        with patch.object(receiver, 'scan_once', side_effect=step) as scan:
            with patch.object(receiver.stop, 'wait', return_value=False):
                receiver.scan()
        self.assertEqual(scan.call_count, 2)

    def test_device_arrival_is_detected_without_restart(self):
        receiver = backend.Receiver()
        info = SimpleNamespace(device='COM99', vid=0x303a, pid=0x1001)
        with patch.object(backend.list_ports, 'comports', return_value=[]):
            receiver.scan_once()
        self.assertIsNone(receiver.port)
        with patch.object(backend.list_ports, 'comports', return_value=[info]):
            with patch.object(backend, 'detect', return_value=(FakeSerial(), 'C3SDR 6 burst 2048')):
                receiver.scan_once()
        self.assertEqual(receiver.info.device, 'COM99')
        receiver.close()

    def test_detection_requires_protocol_identity(self):
        info = SimpleNamespace(device='COM99', vid=0x303a, pid=0x1001)
        with patch.object(backend.serial, 'Serial', FakeSerial):
            port, identity = backend.detect(info)
        self.assertEqual(identity, 'C3SDR 6 burst 2048')
        self.assertIn(b'INFO\n', port.written)
        self.assertFalse(backend.IDENTITY.fullmatch(b'Unrelated serial device'))

    def test_page_and_disconnected_status(self):
        with backend.app.test_client() as client:
            self.assertIn(b'backend-transport.js', client.get('/').data)
            self.assertEqual(client.get('/api/receiver').json['connected'], False)
            with client.get('/backend-transport.js') as response:
                self.assertEqual(response.status_code, 200)

    def test_websocket_commands_exclusivity_and_release(self):
        port = FakeSerial()
        backend.receiver.port = port
        backend.receiver.info = SimpleNamespace(device='COM99', vid=0x303a, pid=0x1001)
        server = make_server('127.0.0.1', 0, backend.app, threaded=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        host = f'127.0.0.1:{server.server_port}'
        try:
            client = Client.connect(f'ws://{host}/serial', headers={'Origin': 'http://127.0.0.1'})
            self.assertTrue(json.loads(client.receive(timeout=2))['ready'])
            other = Client.connect(f'ws://{host}/serial', headers={'Origin': 'http://127.0.0.1'})
            self.assertIn('error', json.loads(other.receive(timeout=2)))
            try:
                other.close()
            except Exception:
                pass
            client.send(json.dumps({'op': 'open', 'baudRate': 1000000, 'id': 1}))
            self.assertEqual(json.loads(client.receive(timeout=2)), {'ack': 1})
            self.assertEqual(port.baudrate, 1000000)
            client.send(b'INFO\n')
            client.send(json.dumps({'op': 'signals', 'signals': {'dataTerminalReady': True}, 'id': 2}))
            self.assertEqual(json.loads(client.receive(timeout=2)), {'ack': 2})
            self.assertIn(b'INFO\n', port.written)
            self.assertTrue(port.dtr)
            client.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
        self.assertTrue(port.closed)
        self.assertFalse(backend.receiver.leased)


if __name__ == '__main__':
    unittest.main()

