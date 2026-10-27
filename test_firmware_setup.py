import io
import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import app as backend
from firmware_setup import SetupInstaller, fingerprint, package


class SetupTests(unittest.TestCase):
    def test_explicit_erase_does_not_write_replacement_firmware(self):
        self.connect_receiver()
        prepared = self.installer.prepare(self.info.device, 'erase')
        self.assertEqual(prepared['operation'], 'erase')
        fake = SimpleNamespace(stdout=io.StringIO('Chip erase completed successfully\n'), wait=lambda: 0, kill=lambda: None)
        with patch('firmware_setup.list_ports.comports', return_value=[self.info]):
            with patch('firmware_setup.subprocess.Popen', return_value=fake) as process:
                self.installer.start(prepared['token'], True, True)
                self.installer.worker.join(timeout=3)
                command = process.call_args.args[0]
        self.assertIn('erase-flash', command)
        self.assertNotIn('write-flash', command)
        self.assertNotIn('--force', command)
        self.assertEqual(self.installer.snapshot()['operation'], 'erase')
        self.assertIn('blank', self.installer.snapshot()['message'])
        self.assertFalse(self.receiver.setup_reserved)

    def connect_receiver(self):
        from test_backend import FakeSerial
        self.receiver.port = FakeSerial()
        self.receiver.info = self.info
        self.receiver.identity = 'C3SDR 6 burst 16380'

    def test_receiver_update_review_and_cancel_leave_reception_untouched(self):
        self.connect_receiver()
        self.receiver.leased = True
        port = self.receiver.port
        prepared = self.installer.prepare(self.info.device, 'update')
        self.assertEqual(prepared['kind'], 'receiver')
        self.assertEqual(prepared['operation'], 'update')
        self.assertIs(self.receiver.port, port)
        self.assertFalse(port.closed)
        self.assertFalse(self.receiver.setup_reserved)

    def test_reinstall_waits_for_viewer_release_then_reserves_same_board(self):
        self.connect_receiver()
        self.receiver.leased = True
        prepared = self.installer.prepare(self.info.device, 'reinstall')
        with patch('firmware_setup.list_ports.comports', return_value=[self.info]):
            with patch('firmware_setup.subprocess.Popen') as process:
                with self.assertRaisesRegex(ValueError, 'in use'):
                    self.installer.start(prepared['token'], True, True)
                process.assert_not_called()
        self.receiver.leased = False
        prepared = self.installer.prepare(self.info.device, 'reinstall')
        port = self.receiver.port
        fake = SimpleNamespace(stdout=io.StringIO('Hash of data verified.\n'), wait=lambda: 0, kill=lambda: None)
        with patch('firmware_setup.list_ports.comports', return_value=[self.info]):
            with patch('firmware_setup.subprocess.Popen', return_value=fake):
                job_id = self.installer.start(prepared['token'], True, True)
                self.installer.worker.join(timeout=3)
        self.assertTrue(port.closed)
        self.assertEqual(self.installer.snapshot()['id'], job_id)
        self.assertEqual(self.installer.snapshot()['state'], 'complete')
        self.assertFalse(self.receiver.setup_reserved)

    def test_guided_reinstall_rejects_other_chip_families(self):
        self.connect_receiver()
        self.receiver.identity = 'S3SDR 6 burst 16380'
        with self.assertRaisesRegex(ValueError, 'XIAO'):
            self.installer.prepare(self.info.device, 'reinstall')

    def setUp(self):
        self.receiver = backend.Receiver()
        self.info = SimpleNamespace(device='COM_TEST', vid=0x303a, pid=0x1001,
                                    serial_number='test-mac', location='USB_TEST', hwid='TEST')
        self.receiver.reports[self.info.device] = {
            'device': self.info.device, 'setup_eligible': True, 'firmware_kind': 'c3cast',
            'fingerprint': fingerprint(self.info), 'identity': 'ESP32DATV 1'}
        self.installer = SetupInstaller(self.receiver, backend.ROOT)

    def test_bundled_package_has_valid_c3_parts(self):
        variant, files = package(backend.ROOT)
        self.assertEqual(variant['target'], 'esp32c3')
        self.assertEqual(files[::2], ['0x0', '0x8000', '0x10000'])

    def test_corrupt_image_fails_before_flash_process(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = backend.ROOT / 'viewer/firmware'
            destination = root / 'viewer/firmware'
            (destination / 'esp32c3').mkdir(parents=True)
            (destination / 'manifest.json').write_bytes((source / 'manifest.json').read_bytes())
            (destination / 'esp32c3/0-bootloader.bin').write_bytes(b'corrupt')
            with patch('firmware_setup.subprocess.Popen') as process:
                with self.assertRaisesRegex(ValueError, 'integrity'):
                    package(root)
                process.assert_not_called()

    def test_review_and_cancel_do_not_touch_flash(self):
        with patch('firmware_setup.subprocess.Popen') as process:
            prepared = self.installer.prepare(self.info.device)
            self.assertEqual(prepared['kind'], 'c3cast')
            self.assertFalse(self.receiver.setup_reserved)
            process.assert_not_called()

    def test_confirmation_missing_or_expired_is_rejected(self):
        prepared = self.installer.prepare(self.info.device)
        with self.assertRaisesRegex(ValueError, 'Confirm'):
            self.installer.start(prepared['token'], True, False)
        self.installer.tokens[prepared['token']] = (time.monotonic() - 1, {})
        with self.assertRaisesRegex(ValueError, 'expired'):
            self.installer.start(prepared['token'], True, True)

    def test_changed_board_at_same_com_port_is_rejected(self):
        prepared = self.installer.prepare(self.info.device)
        changed = SimpleNamespace(**{**vars(self.info), 'serial_number': 'another-board'})
        with patch('firmware_setup.list_ports.comports', return_value=[changed]):
            with patch('firmware_setup.subprocess.Popen') as process:
                with self.assertRaisesRegex(ValueError, 'changed'):
                    self.installer.start(prepared['token'], True, True)
                process.assert_not_called()

    def test_confirmed_install_uses_fixed_c3_layout_and_releases_scanner(self):
        prepared = self.installer.prepare(self.info.device)
        fake = SimpleNamespace(stdout=io.StringIO('Writing 50%\nHash of data verified.\n'), wait=lambda: 0,
                               kill=lambda: None)
        with patch('firmware_setup.list_ports.comports', return_value=[self.info]):
            with patch('firmware_setup.subprocess.Popen', return_value=fake) as process:
                self.installer.start(prepared['token'], True, True)
                self.installer.worker.join(timeout=3)
                args = process.call_args.args[0]
        self.assertIn('--erase-all', args)
        self.assertEqual(args[args.index('--chip') + 1], 'esp32c3')
        self.assertEqual(args[args.index('--port') + 1], 'COM_TEST')
        self.assertNotIn('--force', args)
        self.assertEqual(self.installer.snapshot()['state'], 'complete')
        self.assertFalse(self.receiver.setup_reserved)
        self.assertFalse(self.receiver.reports)
        with self.assertRaisesRegex(ValueError, 'expired'):
            self.installer.start(prepared['token'], True, True)

    def test_flash_failure_is_reported_and_scanning_resumes(self):
        prepared = self.installer.prepare(self.info.device)
        fake = SimpleNamespace(stdout=io.StringIO('Chip type mismatch\n'), wait=lambda: 2, kill=lambda: None)
        with patch('firmware_setup.list_ports.comports', return_value=[self.info]):
            with patch('firmware_setup.subprocess.Popen', return_value=fake):
                self.installer.start(prepared['token'], True, True)
                self.installer.worker.join(timeout=3)
        self.assertEqual(self.installer.snapshot()['state'], 'error')
        self.assertFalse(self.receiver.setup_reserved)

    def test_busy_ports_are_not_setup_candidates(self):
        self.receiver.reports['COM_OTHER'] = {}
        self.assertEqual(len(self.installer.candidates()), 1)
        with self.assertRaisesRegex(ValueError, 'not available'):
            self.installer.prepare('COM_OTHER')

    def test_working_receiver_is_never_offered_for_conversion(self):
        self.receiver.reports[self.info.device].update(firmware_kind='receiver', setup_eligible=False)
        self.assertEqual(self.installer.candidates(), [])

    def test_c3cast_protocol_is_identified_without_starting_installer(self):
        from test_backend import FakeSerial
        class Transmitter(FakeSerial):
            def write(self, data):
                if b'INFO' in data:
                    self.lines.append(b'ESP32DATV 1 PA_GPIO 10 CLEAN_TX 1\r\n')
        report = {}
        with patch.object(backend.serial, 'Serial', Transmitter):
            with patch('firmware_setup.subprocess.Popen') as process:
                self.assertIsNone(backend.detect(self.info, report))
                process.assert_not_called()
        self.assertEqual(report['firmware_kind'], 'c3cast')
        self.assertTrue(report['setup_eligible'])

    def test_port_access_denied_is_not_classified_as_blank(self):
        from test_backend import FakeSerial
        report = {}
        with patch.object(backend.serial, 'Serial', FakeSerial):
            with patch.object(FakeSerial, 'open', side_effect=backend.serial.SerialException('busy')):
                self.assertIsNone(backend.detect(self.info, report))
        self.assertFalse(report)

    def test_setup_post_rejects_other_origins_and_requires_confirmation(self):
        with backend.app.test_client() as client:
            with patch.object(backend.installer, 'start') as start:
                response = client.post('/api/setup/install', json={'confirm_erase': True},
                                       headers={'Origin': 'http://other.example'})
                self.assertEqual(response.status_code, 400)
                start.assert_not_called()


if __name__ == '__main__':
    unittest.main()
