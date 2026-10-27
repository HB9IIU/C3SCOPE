"""One hardware-owning C3SCOPE process per user, even across LAN/local modes."""
import json
import re
import tempfile
import os
from pathlib import Path


class AppInstance:
    def __init__(self, directory=None):
        self.directory = Path(directory) if directory else Path(tempfile.gettempdir()) / 'c3scope-host'
        self.directory.mkdir(parents=True, exist_ok=True)
        self.lock_file = None
        self.state_file = self.directory / 'state.json'

    def acquire(self):
        stream = (self.directory / 'instance.lock').open('a+b')
        stream.seek(0, 2)
        if not stream.tell():
            stream.write(b'0'); stream.flush()
        stream.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            stream.close()
            return False
        self.lock_file = stream
        self.state_file.unlink(missing_ok=True)
        return True

    def publish(self, url, lan):
        temporary = self.directory / 'state.tmp'
        temporary.write_text(json.dumps({'url': url, 'lan': lan}), encoding='utf-8')
        temporary.replace(self.state_file)

    def existing(self):
        try:
            state = json.loads(self.state_file.read_text(encoding='utf-8'))
            return state if re.fullmatch(r'http://127\.0\.0\.1:\d+', state.get('url', '')) else {}
        except (OSError, ValueError):
            return {}

    def release(self):
        if self.lock_file:
            try:
                self.state_file.unlink(missing_ok=True)
            finally:
                self.lock_file.close()
                self.lock_file = None
