import json
import subprocess
import sys
import time
import unittest
import urllib.request
from unittest.mock import patch

from simple_websocket import Client
import app as backend


class LanTests(unittest.TestCase):
    def test_remote_client_cannot_flash_or_quit_even_with_spoofed_forwarded_header(self):
        with backend.app.test_client() as client:
            for route in ('/api/quit', '/api/setup/prepare', '/api/setup/install'):
                with patch.object(backend.receiver.stop, 'set') as stop:
                    response = client.post(route, json={}, environ_overrides={'REMOTE_ADDR': '192.168.1.25'},
                                           headers={'Origin': 'http://localhost', 'X-Forwarded-For': '127.0.0.1'})
                    self.assertEqual(response.status_code, 403)
                    stop.assert_not_called()

    def test_remote_page_gets_remote_capabilities_and_no_firmware_candidates(self):
        with backend.app.test_client() as client:
            page = client.get('/', environ_overrides={'REMOTE_ADDR': '192.168.1.25'})
            self.assertIn(b'"local": false', page.data)
            status = client.get('/api/receiver', environ_overrides={'REMOTE_ADDR': '192.168.1.25'}).json
            self.assertFalse(status['local_control'])
            self.assertFalse(status['can_reinstall'])
            self.assertEqual(status['setup_candidates'], [])

    def test_lan_server_stays_running_after_viewer_close(self):
        script = ('import app; app.receiver.scan=lambda: app.receiver.stop.wait(); '
                  'app.viewer_sessions.grace=.2; app.main(port=0, open_browser=False, lan=True, single_instance=False)')
        process = subprocess.Popen([sys.executable, '-u', '-c', script],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            host = process.stdout.readline().split('http://', 1)[1].split(' ', 1)[0]
            viewer = Client.connect(f'ws://{host}/lifecycle', headers={'Origin': 'http://127.0.0.1'})
            self.assertEqual(json.loads(viewer.receive(timeout=2))['event'], 'ready')
            viewer.close()
            time.sleep(.6)
            self.assertIsNone(process.poll())
            request = urllib.request.Request(f'http://{host}/api/quit', data=b'{}', method='POST',
                                            headers={'Origin': f'http://{host}', 'Content-Type': 'application/json'})
            with urllib.request.urlopen(request, timeout=2) as response:
                self.assertEqual(response.status, 200)
            output, errors = process.communicate(timeout=5)
            self.assertEqual(process.returncode, 0, errors)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()


if __name__ == '__main__':
    unittest.main()
