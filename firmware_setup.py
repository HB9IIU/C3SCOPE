"""Fixed XIAO ESP32-C3 installer. No automatic erase or firmware downloads."""
import hashlib
import importlib.util
import json
import re
import secrets
import subprocess
import sys
import threading
import time
from pathlib import Path

from serial.tools import list_ports


def esptool_command():
    """Portable builds re-run their own exe with --esptool; sources use python -m."""
    if getattr(sys, 'frozen', False):
        return [sys.executable, '--esptool']
    return [sys.executable, '-u', '-m', 'esptool']


def fingerprint(info):
    return (info.device, info.vid, info.pid, getattr(info, 'serial_number', None),
            getattr(info, 'location', None), getattr(info, 'hwid', None))


def package(root):
    directory = Path(root) / 'viewer' / 'firmware'
    variant = json.loads((directory / 'manifest.json').read_text())['variants']['esp32c3']
    if variant['target'] != 'esp32c3' or variant['chip'] != 'ESP32-C3':
        raise ValueError('The bundled firmware is not for ESP32-C3.')
    expected = {'0-bootloader.bin': 0, '1-partition-table.bin': 0x8000, '2-esp_sdr.bin': 0x10000}
    if len(variant['parts']) != 3 or {p['name']: p['offset'] for p in variant['parts']} != expected:
        raise ValueError('Unexpected bundled firmware layout.')
    settings = variant['flash_settings']
    if settings != {'flash_mode': 'dio', 'flash_size': '2MB', 'flash_freq': '80m'}:
        raise ValueError('Unexpected bundled flash settings.')
    files = []
    end = 0
    for part in sorted(variant['parts'], key=lambda p: p['offset']):
        path = directory / 'esp32c3' / part['name']
        data = path.read_bytes()
        if (len(data) != part['size'] or hashlib.sha256(data).hexdigest() != part['sha256']
                or hashlib.md5(data).hexdigest() != part['md5']):
            raise ValueError(f"Bundled firmware integrity check failed: {part['name']}")
        if part['offset'] < end or part['offset'] + len(data) > 2 * 1024 * 1024:
            raise ValueError('Invalid bundled flash addresses.')
        end = part['offset'] + len(data)
        files.extend([hex(part['offset']), str(path)])
    return variant, files


class SetupInstaller:
    def __init__(self, receiver, root):
        self.receiver = receiver
        self.root = root
        self.lock = threading.Lock()
        self.tokens = {}
        self.job = {'state': 'idle', 'message': '', 'log': [], 'progress': None}
        self.process = None
        self.worker = None

    def candidates(self):
        # Reports are published only after a port was successfully opened and
        # identified (or gave no recognized response), never after access denied.
        with self.receiver.lock:
            reports = list(self.receiver.reports.values())
        return [dict(device=r['device'], kind=r['firmware_kind'],
                     identity=r.get('identity'), fingerprint=r['fingerprint'])
                for r in reports if r.get('setup_eligible') and r.get('fingerprint')
                and r.get('firmware_kind') in ('c3cast', 'unknown')]

    def snapshot(self):
        with self.lock:
            return {**self.job, 'log': list(self.job['log'])}

    def prepare(self, device, operation='install'):
        if operation not in ('install', 'update', 'reinstall', 'erase'):
            raise ValueError('Unknown firmware operation.')
        if importlib.util.find_spec('esptool') is None:
            raise ValueError('Flashing support is missing. Install the application requirements first.')
        variant = {'build_date': None} if operation == 'erase' else package(self.root)[0]
        candidate = next((c for c in self.candidates() if c['device'] == device), None)
        if operation in ('update', 'reinstall', 'erase'):
            with self.receiver.lock:
                info = self.receiver.info
                if (self.receiver.port and info and info.device == device
                        and (info.vid, info.pid) == (0x303a, 0x1001)
                        and (self.receiver.identity or '').startswith('C3SDR ')):
                    candidate = {'device': device, 'kind': 'receiver',
                                 'identity': self.receiver.identity, 'fingerprint': fingerprint(info)}
            if not candidate or candidate['kind'] != 'receiver':
                raise ValueError('Connect the XIAO ESP32-C3 receiver before this operation.')
        if not candidate:
            raise ValueError('This device is not available for setup. Wait for detection and retry.')
        candidate['operation'] = operation
        with self.lock:
            if self.job['state'] in ('preparing', 'flashing'):
                raise ValueError('An installation is already running.')
            token = secrets.token_urlsafe(32)
            self.tokens = {token: (time.monotonic() + 120, candidate)}
        return {'token': token, 'device': device, 'kind': candidate['kind'],
                'build_date': variant['build_date'], 'board': 'Seeed Studio XIAO ESP32-C3', 'operation': operation}

    def start(self, token, confirmed_board, confirmed_erase):
        if confirmed_board is not True or confirmed_erase is not True:
            raise ValueError('Confirm the XIAO ESP32-C3 board and firmware erase first.')
        if not isinstance(token, str):
            raise ValueError('Review the selected device before installing.')
        with self.lock:
            if self.job['state'] in ('preparing', 'flashing'):
                raise ValueError('An installation is already running.')
            entry = self.tokens.pop(token, None)
            if not entry or entry[0] < time.monotonic():
                raise ValueError('This confirmation expired. Review the device again.')
            _, candidate = entry
            self.require_same_device(candidate)
            with self.receiver.lock:
                if self.receiver.leased or self.receiver.stop.is_set():
                    raise ValueError('A receiver is in use or the app is stopping. No firmware was erased.')
                if self.receiver.port:
                    if (candidate['kind'] != 'receiver' or not self.receiver.info
                            or fingerprint(self.receiver.info) != tuple(candidate['fingerprint'])):
                        raise ValueError('A different receiver is connected. Nothing was erased.')
                self.receiver.setup_reserved = True
                # The confirming viewer has released its serial session. The
                # scanner may already have reopened the same receiver; reserve
                # and close it atomically before handing it to esptool.
                self.receiver.close()
            self.job = {'id': secrets.token_urlsafe(16), 'operation': candidate.get('operation', 'install'), 'state': 'preparing', 'device': candidate['device'], 'progress': None,
                        'message': 'Preparing the selected board. Keep it connected.', 'log': []}
            self.worker = threading.Thread(target=self.run, args=(candidate,), daemon=True)
            self.worker.start()
            return self.job['id']

    @staticmethod
    def require_same_device(candidate):
        current = next((p for p in list_ports.comports() if p.device == candidate['device']), None)
        if not current or tuple(candidate['fingerprint']) != fingerprint(current):
            raise ValueError('The selected device changed or was unplugged. Nothing was erased; review the board again.')
        if (current.vid, current.pid) != (0x303a, 0x1001):
            raise ValueError('Guided flashing supports the XIAO ESP32-C3 native USB connection only.')

    def update(self, **values):
        with self.lock:
            self.job.update(values)

    def run(self, candidate):
        try:
            # Reserve before waiting for probes, so none can reopen the board
            # between probing and esptool taking exclusive ownership.
            with self.receiver.lock:
                pending = list(self.receiver.probes.values())
                self.receiver.probes.clear()
                self.receiver.probe_fingerprints.clear()
            for future in pending:
                if future.cancel():
                    continue
                found, _ = future.result(timeout=25)
                if found:
                    found[0].close()
            self.require_same_device(candidate)
            erasing = candidate.get('operation') == 'erase'
            files = [] if erasing else package(self.root)[1]  # Recheck before writing.
            if self.receiver.stop.is_set():
                raise ValueError('Installation cancelled because C3SCOPE is stopping.')
            command = [*esptool_command(), '--chip', 'esp32c3',
                       '--port', candidate['device'], '--baud', '460800',
                       '--before', 'default-reset', '--after', 'hard-reset']
            command += ['erase-flash'] if erasing else ['write-flash', '--erase-all', '--flash-mode', 'dio',
                                                       '--flash-freq', '80m', '--flash-size', '2MB', *files]
            self.update(state='flashing', message=('Erasing this ESP32. ' if erasing else 'Installing receiver firmware. ') + 'Do not unplug the board or close C3SCOPE.')
            # esptool validates chip type before erase, checks flash protection,
            # and verifies every written image. Never pass --force.
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                       text=True, encoding='utf-8', errors='replace',
                                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            self.process = process
            if self.receiver.stop.is_set():
                process.terminate()
            watchdog = threading.Timer(180, process.kill)
            watchdog.daemon = True
            watchdog.start()
            try:
                for line in process.stdout:
                    line = line.strip()
                    if line:
                        with self.lock:
                            self.job['log'] = (self.job['log'] + [line])[-150:]
                            match = re.search(r'(\d+(?:\.\d+)?)\s*%', line)
                            self.job['progress'] = min(99, int(float(match[1]))) if match else self.job['progress']
                code = process.wait()
            finally:
                watchdog.cancel()
                process.stdout.close()
                self.process = None
            if code != 0:
                raise ValueError('Installation did not complete. Close other serial applications. If needed, hold BOOT while connecting the XIAO, then retry. See details below.')
            self.update(state='complete', progress=100,
                        message='ESP32 erased. This board is now blank. Install receiver firmware below to use C3SCOPE again.' if erasing else 'Firmware written and verified. Reconnecting automatically…')
        except Exception as exc:
            self.update(state='error', message=str(exc), progress=None)
        finally:
            with self.receiver.lock:
                self.receiver.reports.clear()
                self.receiver.next_probe.clear()
                self.receiver.setup_reserved = False

    def stop(self):
        process = self.process
        if process and process.poll() is None:
            process.terminate()
