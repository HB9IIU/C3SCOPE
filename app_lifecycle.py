"""Track actual open viewer sockets, with a grace period for page reloads."""
import threading
import time


class ViewerSessions:
    def __init__(self, grace=10, clock=time.monotonic):
        self.lock = threading.Lock()
        self.grace = grace
        self.clock = clock
        self.sockets = set()
        self.seen_viewer = False
        self.empty_since = None

    def opened(self, socket):
        with self.lock:
            self.seen_viewer = True
            self.sockets.add(socket)
            self.empty_since = None

    def browser_activity(self):
        # Compatibility fallback for a tab loaded before lifetime sockets were
        # introduced, or a browser that fails to establish that socket.
        with self.lock:
            self.seen_viewer = True
            if not self.sockets:
                self.empty_since = self.clock()

    def closed(self, socket):
        with self.lock:
            self.sockets.discard(socket)
            if not self.sockets and self.empty_since is None:
                self.empty_since = self.clock()

    def should_stop(self, installing=False):
        with self.lock:
            if not self.seen_viewer or self.sockets:
                return False
            if installing:
                # Never shut down a flash just because its browser disappeared.
                self.empty_since = self.clock()
                return False
            return self.empty_since is not None and self.clock() - self.empty_since >= self.grace

    def notify_stopping(self):
        with self.lock:
            sockets = list(self.sockets)
        for socket in sockets:
            try:
                socket.send('{"event":"stopping"}')
                socket.close()
            except Exception:
                pass
