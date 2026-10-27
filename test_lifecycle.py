import json
import subprocess
import sys
import threading
import time
import unittest
import urllib.request
import socket
import contextlib
import io
from unittest.mock import patch

from simple_websocket import Client
from app_lifecycle import ViewerSessions
import app as backend


class LifecycleTests(unittest.TestCase):
    def test_occupied_port_selects_next_available_bound_server(self):
        with socket.socket() as occupied:
            occupied.bind(('127.0.0.1', 0))
            occupied.listen()
            first = occupied.getsockname()[1]
            with contextlib.redirect_stderr(io.StringIO()):
                server = backend.create_local_server(first)
            try:
                self.assertGreater(server.server_port, first)
                self.assertLess(server.server_port, first + 20)
            finally:
                server.server_close()

    def test_exhausted_port_range_fails_clearly(self):
        with patch.object(backend, 'bind_server', side_effect=SystemExit(1)) as factory:
            with self.assertRaisesRegex(RuntimeError, '8000 to 8019'):
                backend.create_local_server()
            self.assertEqual(factory.call_count, 20)

    def test_startup_browser_uses_server_url_and_failure_is_nonfatal(self):
        with patch.object(backend.webbrowser, 'open', return_value=True) as browser:
            backend.open_startup_page('http://127.0.0.1:8000')
            browser.assert_called_once_with('http://127.0.0.1:8000', new=2)
        with patch.object(backend.webbrowser, 'open', side_effect=OSError('no browser')):
            with self.assertLogs(level='ERROR'):
                backend.open_startup_page('http://127.0.0.1:8000')

    def test_legacy_page_polling_keeps_server_alive_then_expires(self):
        now = [0]
        sessions = ViewerSessions(clock=lambda: now[0])
        sessions.browser_activity()
        now[0] = 9
        sessions.browser_activity()
        now[0] = 15
        self.assertFalse(sessions.should_stop())
        now[0] = 20
        self.assertTrue(sessions.should_stop())

    def test_real_server_stops_when_legacy_browser_polling_ends(self):
        script = ('import app; app.receiver.scan=lambda: app.receiver.stop.wait(); '
                  'app.viewer_sessions.grace=.5; app.main(port=0, open_browser=False, single_instance=False)')
        process = subprocess.Popen([sys.executable, '-u', '-c', script],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            host = process.stdout.readline().split('http://', 1)[1].split(' ', 1)[0]
            request = urllib.request.Request(f'http://{host}/api/receiver', headers={'User-Agent': 'Mozilla/5.0 regression-test'})
            with urllib.request.urlopen(request, timeout=2) as response:
                self.assertEqual(response.status, 200)
            output, errors = process.communicate(timeout=5)
            self.assertEqual(process.returncode, 0, errors)
            self.assertIn('Serial port released.', output)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()

    def test_no_shutdown_before_first_viewer_and_reload_has_grace(self):
        now = [0]
        sessions = ViewerSessions(clock=lambda: now[0])
        now[0] = 100
        self.assertFalse(sessions.should_stop())
        sessions.opened('first')
        sessions.closed('first')
        now[0] = 105
        self.assertFalse(sessions.should_stop())
        sessions.opened('reload')
        now[0] = 120
        self.assertFalse(sessions.should_stop())
        sessions.closed('reload')
        now[0] = 131
        self.assertTrue(sessions.should_stop())

    def test_only_last_tab_close_counts_and_flashing_delays_shutdown(self):
        now = [0]
        sessions = ViewerSessions(clock=lambda: now[0])
        sessions.opened('one'); sessions.opened('two')
        sessions.closed('one')
        now[0] = 100
        self.assertFalse(sessions.should_stop())
        sessions.closed('two')
        now[0] = 120
        self.assertFalse(sessions.should_stop(installing=True))
        now[0] = 125
        self.assertFalse(sessions.should_stop())
        now[0] = 131
        self.assertTrue(sessions.should_stop())

    def test_quit_requires_local_origin_and_is_blocked_during_flash(self):
        with backend.app.test_client() as client:
            with patch.object(backend.receiver, 'stop', threading.Event()) as stop:
                self.assertEqual(client.post('/api/quit', json={}, headers={'Origin': 'https://other.example'}).status_code, 400)
                self.assertFalse(stop.is_set())
                with patch.dict(backend.installer.job, state='flashing'):
                    self.assertEqual(client.post('/api/quit', json={}, headers={'Origin': 'http://localhost'}).status_code, 409)
                    self.assertFalse(stop.is_set())
                with patch.dict(backend.installer.job, state='idle'):
                    self.assertEqual(client.post('/api/quit', json={}, headers={'Origin': 'http://localhost'}).status_code, 200)
                    self.assertTrue(stop.is_set())

    def test_real_server_exits_after_last_tab_closes_but_survives_reload(self):
        script = ('import app; app.receiver.scan=lambda: app.receiver.stop.wait(); '
                  'app.viewer_sessions.grace=.5; app.main(port=0, open_browser=False, single_instance=False)')
        process = subprocess.Popen([sys.executable, '-u', '-c', script],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        clients = []
        try:
            startup = process.stdout.readline()
            host = startup.split('http://', 1)[1].split(' ', 1)[0]
            def connect():
                client = Client.connect(f'ws://{host}/lifecycle', headers={'Origin': 'http://127.0.0.1'})
                clients.append(client)
                self.assertEqual(json.loads(client.receive(timeout=2))['event'], 'ready')
                return client
            one = connect()
            one.close()  # Refresh the only tab.
            two = connect()
            three = connect()
            time.sleep(.65)
            self.assertIsNone(process.poll())
            two.close()
            time.sleep(.65)
            self.assertIsNone(process.poll())
            three.close()
            output, errors = process.communicate(timeout=5)
            self.assertEqual(process.returncode, 0, errors)
            self.assertIn('Serial port released.', output)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()
            for client in clients:
                try:
                    client.close()
                except Exception:
                    pass


if __name__ == '__main__':
    unittest.main()
