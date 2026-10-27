import tempfile
import unittest
import contextlib
import io
from unittest.mock import patch

from app_instance import AppInstance
import app as backend


class InstanceTests(unittest.TestCase):
    def test_wildcard_listener_cannot_be_shadowed_by_a_local_listener(self):
        first = backend.bind_server('0.0.0.0', 0)
        second = None
        try:
            with contextlib.redirect_stderr(io.StringIO()):
                second = backend.create_local_server(first.server_port, '127.0.0.1')
            self.assertNotEqual(first.server_port, second.server_port)
        finally:
            if second:
                second.server_close()
            first.server_close()
    def test_duplicate_is_refused_and_existing_url_is_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            first = AppInstance(directory)
            second = AppInstance(directory)
            try:
                self.assertTrue(first.acquire())
                first.publish('http://127.0.0.1:8001', True)
                self.assertFalse(second.acquire())
                self.assertEqual(second.existing(), {'url': 'http://127.0.0.1:8001', 'lan': True})
            finally:
                first.release()
                second.release()

    def test_lock_is_available_after_shutdown(self):
        with tempfile.TemporaryDirectory() as directory:
            first = AppInstance(directory)
            self.assertTrue(first.acquire())
            first.release()
            second = AppInstance(directory)
            try:
                self.assertTrue(second.acquire())
            finally:
                second.release()

    def test_second_start_never_launches_another_server(self):
        with tempfile.TemporaryDirectory() as directory:
            first = AppInstance(directory)
            self.assertTrue(first.acquire())
            first.publish('http://127.0.0.1:8000', True)
            try:
                with patch.object(backend, 'AppInstance', side_effect=lambda: AppInstance(directory)):
                    with patch.object(backend, 'run_server') as run:
                        backend.main(open_browser=False)
                        run.assert_not_called()
            finally:
                first.release()


if __name__ == '__main__':
    unittest.main()
