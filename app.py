"""Local spectrum viewer and automatically discovered ESP-SDR serial bridge."""
import json
import logging
import re
import signal
import sys
import threading
import time
import webbrowser
import argparse
import ipaddress
import socket
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import serial
from serial.tools import list_ports
from flask import Flask, jsonify, request
from flask_sock import Sock
from werkzeug.serving import make_server, ThreadedWSGIServer
from firmware_setup import SetupInstaller, fingerprint
from app_lifecycle import ViewerSessions
from app_instance import AppInstance
from serial_policy import validate_remote_write

ROOT = Path(__file__).resolve().parent
app = Flask(__name__, static_folder=str(ROOT / 'viewer'), static_url_path='')
app.config['SOCK_SERVER_OPTIONS'] = {'ping_interval': 10, 'max_message_size': 131072}
app.config['LAN_ENABLED'] = False
app.config['LAN_URLS'] = []
app.config['TRUSTED_HOSTS'] = ['localhost', '127.0.0.1', '[::1]']
app.config['MAX_CONTENT_LENGTH'] = 16384
sock = Sock(app)
IDENTITY = re.compile(rb'^(ESP32|C2|C3|C5|C6|C61|H2|S2|S3|S31)SDR 6 burst \d+$')
REPORT_GRACE = 12  # seconds a board may be missing from USB before it is forgotten
REPORT_KEEP = 30   # seconds a good probe result outlives failed re-probes
probe_status = {'state': 'searching', 'message': 'Connect an ESP-SDR receiver by USB. Detection is automatic.'}


def detect(info, report=None):
    """Confirm the firmware protocol, never select a board from its VID alone."""
    standalone = report is None
    report = probe_status if standalone else report
    for baud in ((2000000,) if info.vid == 0x303a else (2000000, 1000000, 115200)):
        port = serial.Serial(port=None, baudrate=baud, timeout=.1, write_timeout=2)
        port.dtr = False
        port.rts = False
        port.port = info.device
        try:
            port.open()
            report.update(device=info.device, fingerprint=fingerprint(info),
                          setup_eligible=(info.vid, info.pid) == (0x303a, 0x1001))
            if info.vid == 0x303a and info.pid != 0x0002:
                port.dtr = True
            # INFO is read-only and also identifies incompatible firmware.
            port.write(b'\nINFO\n')
            info_deadline = time.monotonic() + 1
            retry_info = time.monotonic() + .25
            while time.monotonic() < info_deadline:
                if receiver.stop.is_set():
                    port.close()
                    return None
                if time.monotonic() >= retry_info:
                    port.write(b'INFO\n')
                    retry_info = time.monotonic() + .25
                identity = port.readline().strip()
                if IDENTITY.fullmatch(identity):
                    report.update(setup_eligible=False, firmware_kind='receiver')
                    port.timeout = .01
                    return port, identity.decode()
                if identity.startswith(b'ESP32DATV '):
                    report.update(firmware_kind='c3cast', identity=identity.decode(errors='replace'))
                    report['state'] = 'incompatible'
                    report['message'] = (
                        f'We found your ESP32 on {info.device}.\n'
                        'It is running DATV transmitter firmware.\n'
                        'You can leave it connected!\n\n'
                        'But!!!\n'
                        'To see your signal, C3SCOPE needs a receiver too.\n'
                        'Plug in an additional ESP-SDR receiver.\n'
                        'We will connect it automatically.')
                    logging.debug(report['message'])
                    port.close()
                    return None
            for attempt in range(3):
                if receiver.stop.is_set():
                    port.close()
                    return None
                marker = f'SYNC {time.monotonic_ns()}'.encode()
                port.write(b'\n' + marker + b'\n')
                deadline = time.monotonic() + 1.5
                while time.monotonic() < deadline:
                    if receiver.stop.is_set():
                        port.close()
                        return None
                    if port.readline().strip() == marker:
                        port.write(b'INFO\n')
                        identity = port.readline().strip()
                        if IDENTITY.fullmatch(identity):
                            report.update(setup_eligible=False, firmware_kind='receiver')
                            port.timeout = .01
                            return port, identity.decode()
                        break
            port.close()
        except (serial.SerialException, OSError) as exc:
            # An inaccessible port has not been identified as our receiver.
            # It may belong to another application; leave it alone and keep
            # the waiting/identified-device message instead of reporting fault.
            logging.debug('Skipping unavailable port %s: %s', info.device, exc)
            if not standalone:
                report.clear()
            port.close()
            return None
    if report.get('setup_eligible'):
        report.update(state='unrecognized', firmware_kind='unknown',
                      message='An ESP USB device was found. Its firmware is blank or not recognized.\nGuided setup is for the Seeed Studio XIAO ESP32-C3 only.')
    return None


class Receiver:
    def __init__(self):
        self.lock = threading.Lock()
        self.port = None
        self.info = None
        self.identity = None
        self.leased = False
        self.stop = threading.Event()
        self.port_signature = None
        self.executor = None
        self.probes = {}
        self.probe_fingerprints = {}
        self.next_probe = {}
        self.reports = {}
        self.report_time = {}
        self.missing_since = {}
        self.setup_reserved = False

    def close(self):
        if self.port:
            self.port.close()
        self.port = None

    def scan(self):
        self.executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix='usb-probe')
        try:
            while not self.stop.is_set():
                try:
                    self.scan_once()
                except Exception:
                    logging.exception('USB scan failed; retrying')
                self.stop.wait(.5)
        finally:
            self.executor.shutdown(wait=True, cancel_futures=True)
            for future in self.probes.values():
                if not future.cancelled() and future.done() and not future.exception():
                    found, _ = future.result()
                    if found:
                        found[0].close()

    def probe(self, info):
        report = {}
        return detect(info, report), report

    def scan_once(self):
        if self.setup_reserved:
            return
        if self.executor:
            self.scan_concurrently()
            return
        with self.lock:
            ports = list(list_ports.comports())
            if self.port and not self.leased and not any(p.device == self.info.device for p in ports):
                self.close()
            if not self.port:
                signature = tuple(sorted((p.device, p.vid, p.pid) for p in ports))
                if signature != self.port_signature:
                    probe_status.update(state='searching', message='Connect an ESP-SDR receiver by USB. Detection is automatic.')
                    self.port_signature = signature
                # Enumerate every COM port; probe USB serial devices only, to
                # avoid sending SDR commands to unrelated built-in ports.
                for info in sorted(ports, key=lambda p: p.vid != 0x303a):
                    if info.vid is None:
                        continue
                    found = detect(info)
                    if found:
                        self.port, self.identity = found
                        self.info = info
                        logging.info('Detected %s on %s', self.identity, info.device)
                        break

    def scan_concurrently(self):
        # Enumerate frequently; a slow/unrelated port never blocks hot-plug
        # discovery or a browser claiming an already identified receiver.
        listed = list(list_ports.comports())
        ports = {p.device: p for p in listed if p.vid is not None}
        with self.lock:
            if self.setup_reserved:
                return
            if self.port and not self.leased and (self.info.device not in ports
                    or fingerprint(self.info) != fingerprint(ports[self.info.device])):
                self.close()
            for device, future in list(self.probes.items()):
                if not future.done():
                    continue
                del self.probes[device]
                self.next_probe[device] = time.monotonic() + 5
                found, report = future.result()
                expected = self.probe_fingerprints.pop(device, None) or report.get('fingerprint')
                if device not in ports or (expected and tuple(expected) != fingerprint(ports[device])):
                    if found:
                        found[0].close()
                    if device in ports:
                        # A different USB device now uses this COM name.
                        self.reports.pop(device, None)
                        self.next_probe.pop(device, None)
                    # Otherwise the board is only missing for the moment (an ESP32
                    # re-enumerates when it resets); the grace period below keeps
                    # what we already know instead of flashing back to "searching".
                    continue
                now = time.monotonic()
                previous = self.reports.get(device)
                if report or not previous or now - self.report_time.get(device, 0) > REPORT_KEEP:
                    # An empty report means this probe could not open the port.
                    # Do not let one failed attempt erase a recent good result.
                    self.reports[device] = report
                    self.report_time[device] = now
                if found:
                    if device in ports and not self.port:
                        self.port, self.identity = found
                        self.info = ports[device]
                        logging.info('Detected %s on %s', self.identity, device)
                    else:
                        found[0].close()
            now = time.monotonic()
            for device in list(self.missing_since):
                if device in ports:
                    del self.missing_since[device]
            for device in set(self.reports) - set(ports):
                if now - self.missing_since.setdefault(device, now) > REPORT_GRACE:
                    self.reports.pop(device, None)
                    self.report_time.pop(device, None)
                    self.next_probe.pop(device, None)
                    self.missing_since.pop(device, None)
            for device, report in list(self.reports.items()):
                if device in ports and report.get('fingerprint') and tuple(report['fingerprint']) != fingerprint(ports[device]):
                    self.reports.pop(device, None)
                    self.report_time.pop(device, None)
                    self.next_probe.pop(device, None)
            report = next((r for r in self.reports.values() if r.get('state') == 'incompatible'), None)
            report = report or next((r for r in self.reports.values() if r.get('state') == 'unrecognized'), None)
            probe_status.update(report or {'state': 'searching', 'message': 'Connect an ESP-SDR receiver by USB. Detection is automatic.'})
            clash = [p.description for p in listed if report and p.device == report.get('device') and p.vid is None]
            if clash:
                # Virtual COM ports from radio software can share a name with the
                # board; Windows then sends that name to only one of them.
                probe_status['message'] += (
                    f"\n\nWindows also lists {'; '.join(clash)}. Two devices cannot share a COM name, so this board "
                    'cannot be reached. In Device Manager, open Ports (COM & LPT), double-click the board '
                    '(USB Serial Device), choose Port Settings, Advanced, pick another COM port number, '
                    'then unplug and replug it.')
            if not self.port:
                for info in sorted(ports.values(), key=lambda p: p.vid != 0x303a):
                    if info.device not in self.probes and time.monotonic() >= self.next_probe.get(info.device, 0):
                        self.probes[info.device] = self.executor.submit(self.probe, info)
                        self.probe_fingerprints[info.device] = fingerprint(info)


receiver = Receiver()
installer = SetupInstaller(receiver, ROOT)
viewer_sessions = ViewerSessions(grace=10)
active_sockets = set()


def local_browser():
    try:
        return ipaddress.ip_address(request.remote_addr or '').is_loopback
    except ValueError:
        return False


def lan_urls(port):
    try:
        addresses = {entry[4][0] for entry in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)}
        return [f'http://{address}:{port}' for address in sorted(addresses)
                if ipaddress.ip_address(address).is_private
                and not ipaddress.ip_address(address).is_loopback
                and not ipaddress.ip_address(address).is_link_local]
    except OSError:
        return []


@app.before_request
def track_viewer_activity():
    if (request.method == 'POST' and request.path in ('/api/quit', '/api/setup/prepare', '/api/setup/install')
            and not local_browser()):
        return jsonify(error='Firmware operations and quitting are available only on the host PC.'), 403
    # Browser polling also counts, so an already-open older page can still
    # trigger shutdown when closed. CLI health checks must not arm auto-quit.
    if request.path in ('/', '/api/receiver') and 'Mozilla/' in request.headers.get('User-Agent', ''):
        viewer_sessions.browser_activity()


@app.get('/')
def index():
    html = (ROOT / 'viewer/index.html').read_text(encoding='utf-8')
    access = {'local': local_browser(), 'lan': app.config['LAN_ENABLED'],
              'urls': app.config['LAN_URLS'], 'auto_shutdown': not app.config['LAN_ENABLED']}
    html = html.replace('</head>', '<script>globalThis.C3ScopeAccess = ' + json.dumps(access) + ';</script></head>')
    panel = '''<section id="receiverWaiting" role="status" aria-live="polite">
      <div class="receiver-waiting-card">
        <img class="receiver-search-symbol" src="c3scope.svg" alt="">
        <div class="receiver-waiting-label">C3SCOPE · SEE YOUR SIGNAL.</div>
        <h2 id="receiverWaitingTitle">Searching for your receiver</h2>
        <p id="receiverWaitingMessage">Connect your ESP-SDR receiver by USB.</p>
        <div id="setupDevices"></div>
        <div id="setupProgress" hidden>
          <p id="setupProgressText"></p>
          <progress id="setupProgressBar" max="100" aria-label="Current firmware image progress"></progress>
          <details><summary>Installation details</summary><pre id="setupLog"></pre></details>
        </div>
        <p id="setupError" role="alert" hidden></p>
        <div class="receiver-search-progress" aria-hidden="true"><span></span></div>
        <small>Connects automatically when a compatible receiver is found.</small>
      </div>
    </section>'''
    html = html.replace('<body>', '<body class="receiver-waiting">').replace('<main>', panel + '<main>')
    html = html.replace('<script defer src="radio.js">', '<script defer src="backend-transport.js"></script>\n    <script defer src="radio.js">')
    html = html.replace('</body>', '<script defer src="setup.js"></script><script defer src="lifecycle.js"></script></body>')
    for name in ('serial-transport.js', 'backend-transport.js', 'setup.js', 'lifecycle.js', 'radio.js', 'datv.js', 'app.js', 'instrument.css', 'c3scope.svg'):
        version = (ROOT / 'viewer' / name).stat().st_mtime_ns
        html = html.replace(f'"{name}"', f'"{name}?v={version}"')
    return html


@app.after_request
def fresh_local_files(response):
    response.headers['Cache-Control'] = 'no-store'
    return response


@app.get('/api/receiver')
def status():
    # Do not block status requests while the scanner is probing an absent board.
    info = receiver.info if receiver.port else None
    return jsonify(connected=bool(info), busy=receiver.leased,
                   device=info.device if info else None,
                   vid=info.vid if info else None, pid=info.pid if info else None,
                   identity=receiver.identity if info else None,
                   local_control=local_browser(), lan_enabled=app.config['LAN_ENABLED'],
                   can_reinstall=bool(local_browser() and info and (info.vid, info.pid) == (0x303a, 0x1001)
                                      and (receiver.identity or '').startswith('C3SDR ')),
                   state='ready' if info else probe_status['state'],
                   message=probe_status['message'],
                   setup_candidates=installer.candidates() if local_browser() else [],
                   installation=installer.snapshot() if local_browser() else {'state': installer.snapshot()['state']})


def local_setup_request():
    if not local_browser():
        raise ValueError('Firmware operations and quitting are available only on the host PC.')
    if request.headers.get('Origin') != f'http://{request.host}' or not request.is_json:
        raise ValueError('Requests must come from this local C3SCOPE page.')
    data = request.get_json()
    if not isinstance(data, dict):
        raise ValueError('Expected a JSON object.')
    return data


@app.post('/api/setup/prepare')
def setup_prepare():
    try:
        data = local_setup_request()
        return jsonify(installer.prepare(data.get('device'), data.get('operation', 'install')))
    except (ValueError, OSError, KeyError) as exc:
        return jsonify(error=str(exc)), 400


@app.post('/api/setup/install')
def setup_install():
    try:
        data = local_setup_request()
        job_id = installer.start(data.get('token'), data.get('confirm_board'), data.get('confirm_erase'))
        return jsonify(started=True, job_id=job_id), 202
    except (ValueError, OSError, KeyError) as exc:
        return jsonify(error=str(exc)), 400


@app.post('/api/quit')
def quit_app():
    try:
        local_setup_request()
        with installer.lock:
            if installer.job['state'] in ('preparing', 'flashing'):
                return jsonify(error='Firmware installation is in progress. Let it finish before quitting.'), 409
            receiver.stop.set()
        return jsonify(stopped=True)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400


@sock.route('/lifecycle')
def lifecycle(ws):
    if request.headers.get('Origin') != f'http://{request.host}':
        ws.close()
        return
    viewer_sessions.opened(ws)
    try:
        ws.send(json.dumps({'event': 'ready', 'close_grace_seconds': viewer_sessions.grace}))
        # WebSocket pings are answered by the browser even in a background tab.
        # A page close/crash closes the socket; reload gets a grace period.
        while not receiver.stop.is_set():
            ws.receive(timeout=1)
        ws.send('{"event":"stopping"}')
    except Exception:
        pass
    finally:
        viewer_sessions.closed(ws)
        try:
            ws.close()
        except Exception:
            pass


@sock.route('/serial')
def bridge(ws):
    # Only this local origin may control the serial device.
    if request.headers.get('Origin') != f'http://{request.host}':
        ws.close()
        return
    remote = not local_browser()
    with receiver.lock:
        if receiver.setup_reserved or receiver.leased or not receiver.port:
            ws.send(json.dumps({'error': 'Receiver unavailable or already in use'}))
            return
        receiver.leased = True
        port = receiver.port
    try:
        active_sockets.add(ws)
        ws.send(json.dumps({'ready': True}))
        while not receiver.stop.is_set():
            message = ws.receive(timeout=.001)
            if isinstance(message, bytes):
                if remote:
                    validate_remote_write(message)
                port.write(message)
            elif isinstance(message, str):
                command = json.loads(message)
                if command['op'] == 'open':
                    if remote and command.get('baudRate') not in (115200, 1000000, 2000000):
                        raise ValueError('Unsupported receiver baud rate.')
                    port.baudrate = int(command['baudRate'])
                elif command['op'] == 'signals':
                    signals = command['signals']
                    if remote and (signals.get('requestToSend') not in (None, False)
                                   or set(signals) - {'dataTerminalReady', 'requestToSend'}):
                        raise ValueError('Bootloader control is not available to LAN viewers.')
                    if 'dataTerminalReady' in signals:
                        port.dtr = bool(signals['dataTerminalReady'])
                    if 'requestToSend' in signals:
                        port.rts = bool(signals['requestToSend'])
                else:
                    raise ValueError('Unknown serial operation')
                ws.send(json.dumps({'ack': command['id']}))
            data = port.read(min(max(port.in_waiting, 1), 65536))
            if data:
                ws.send(data)
    except Exception as exc:
        logging.info('Serial session ended: %s', exc)
    finally:
        active_sockets.discard(ws)
        with receiver.lock:
            receiver.close()
            receiver.leased = False
        try:
            ws.close()
        except Exception:
            pass


def open_startup_page(url):
    try:
        if not webbrowser.open(url, new=2):
            logging.warning('Browser could not be opened. Open %s manually.', url)
    except Exception:
        logging.exception('Browser could not be opened. Open %s manually.', url)


class ExclusiveServer(ThreadedWSGIServer):
    allow_reuse_address = False

    def server_bind(self):
        if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def bind_server(host, port):
    if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
        return ExclusiveServer(host, port, app)
    return make_server(host, port, app, threaded=True)


def create_local_server(first_port=8000, host='127.0.0.1'):
    # Bind the server itself, rather than testing and releasing a socket first.
    # This avoids a race with another app starting on the selected port.
    for port in range(first_port, first_port + 20) if first_port else (0,):
        try:
            return bind_server(host, port)
        except SystemExit as exc:
            # Werkzeug reports bind failures with SystemExit. Only continue
            # for the ordinary bind-failure exit; do not swallow interrupts.
            if exc.code != 1:
                raise
    raise RuntimeError(f'No available local port from {first_port} to {first_port + 19}. Close another C3SCOPE instance and retry.')


def main(port=8000, open_browser=True, lan=False, single_instance=True):
    instance = AppInstance() if single_instance else None
    if instance and not instance.acquire():
        existing = instance.existing()
        print('C3SCOPE is already running. Reusing it; no second receiver scanner was started.', flush=True)
        if existing:
            print(f"Existing {'LAN' if existing.get('lan') else 'local'} app: {existing['url']}", flush=True)
            if lan and not existing.get('lan'):
                print('Quit the existing local app before restarting with --lan.', flush=True)
            if open_browser:
                open_startup_page(existing['url'])
        return
    try:
        run_server(port, open_browser, lan, instance)
    finally:
        if instance:
            instance.release()


def run_server(port, open_browser, lan, instance=None):
    logging.basicConfig(level=logging.INFO)
    def request_shutdown(signum, frame):
        receiver.stop.set()

    signal.signal(signal.SIGINT, request_shutdown)
    signal.signal(signal.SIGTERM, request_shutdown)
    if hasattr(signal, 'SIGBREAK'):
        signal.signal(signal.SIGBREAK, request_shutdown)
    app.config['LAN_ENABLED'] = lan
    server = create_local_server(port, host='0.0.0.0' if lan else '127.0.0.1')
    app.config['LAN_URLS'] = lan_urls(server.server_port) if lan else []
    from urllib.parse import urlsplit
    app.config['TRUSTED_HOSTS'] = ['localhost', '127.0.0.1', '[::1]'] + [urlsplit(u).hostname for u in app.config['LAN_URLS']]
    # A bounded accept wait lets Windows process console signals promptly.
    server.timeout = .25
    scanner = threading.Thread(target=receiver.scan, daemon=True)
    scanner.start()
    url = f'http://127.0.0.1:{server.server_port}'
    if instance:
        instance.publish(url, lan)
    print(f'C3SCOPE running at {url} — Ctrl+C to stop.', flush=True)
    if lan:
        for address in app.config['LAN_URLS']:
            print(f'LAN viewer: {address}', flush=True)
        print('LAN mode: close the host viewer before opening another viewer. Use Quit on the host or Ctrl+C to stop.', flush=True)
    if open_browser:
        # The socket is already bound. Launch without delaying request handling.
        threading.Thread(target=open_startup_page, args=(url,), daemon=True).start()
    try:
        while not receiver.stop.is_set():
            server.handle_request()
            if not lan and viewer_sessions.should_stop(installer.snapshot()['state'] in ('preparing', 'flashing')):
                logging.info('Last viewer closed. Stopping C3SCOPE.')
                receiver.stop.set()
    finally:
        receiver.stop.set()
        viewer_sessions.notify_stopping()
        installer.stop()
        server.server_close()
        for ws in list(active_sockets):
            try:
                ws.close()
            except Exception:
                pass
        scanner.join(timeout=2)
        receiver.close()
        print('C3SCOPE stopped. Serial port released.', flush=True)


if __name__ == '__main__':
    if getattr(sys, 'frozen', False) and sys.argv[1:2] == ['--esptool']:
        import esptool
        esptool.main(sys.argv[2:])
        raise SystemExit(0)
    parser = argparse.ArgumentParser(description='C3SCOPE spectrum viewer')
    parser.add_argument('--lan', action='store_true', help='Allow LAN viewers; keep running when browser tabs close')
    parser.add_argument('--port', type=int, default=8000, help='First port to try (default: 8000)')
    parser.add_argument('--no-browser', action='store_true', help='Do not open the host browser')
    args = parser.parse_args()
    main(port=args.port, open_browser=not args.no_browser, lan=args.lan)
