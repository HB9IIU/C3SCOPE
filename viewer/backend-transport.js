// SerialPort-compatible transport for the local Flask/pyserial server.
(function () {
  'use strict';
  class BackendPort {
    constructor(info) { this.info = info; this.kind = 'backend'; this.pending = new Map(); this.nextId = 0; }
    getInfo() { return { usbVendorId: this.info.vid, usbProductId: this.info.pid }; }
    async open({ baudRate }) {
      this.socket = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/serial`);
      this.socket.binaryType = 'arraybuffer';
      this.readable = new ReadableStream({ start: c => { this.controller = c; }, cancel: () => this.close() });
      this.writable = new WritableStream({ write: bytes => {
        if (this.socket.readyState !== WebSocket.OPEN) throw Error('Backend connection closed');
        this.socket.send(bytes);
      } });
      await new Promise((resolve, reject) => {
        this.socket.onmessage = ({ data }) => {
          if (typeof data !== 'string') { this.controller.enqueue(new Uint8Array(data)); return; }
          const message = JSON.parse(data);
          if (message.error) { reject(Error(message.error)); return; }
          if (message.ready) resolve();
          if (message.ack) { this.pending.get(message.ack)?.resolve(); this.pending.delete(message.ack); }
        };
        this.socket.onerror = () => reject(Error('Cannot connect to local serial server'));
        this.socket.onclose = () => {
          reject(Error('Local serial connection closed'));
          for (const pending of this.pending.values()) pending.reject(Error('Local serial connection closed'));
          this.pending.clear();
          try { this.controller.error(Error('Receiver disconnected')); } catch {}
        };
      });
      await this.control({ op: 'open', baudRate });
    }
    control(command) {
      return new Promise((resolve, reject) => {
        const id = ++this.nextId;
        this.pending.set(id, { resolve, reject });
        this.socket.send(JSON.stringify({ ...command, id }));
      });
    }
    setSignals(signals) { return this.control({ op: 'signals', signals }); }
    async close() {
      const socket = this.socket;
      if (!socket || socket.readyState === WebSocket.CLOSED) return;
      await new Promise(resolve => {
        socket.addEventListener('close', resolve, { once: true });
        socket.close();
      });
    }
  }
  let statusRequest = null;
  const refreshStatus = () => statusRequest ||= (async () => {
    const response = await fetch('/api/receiver', { cache: 'no-store', signal: AbortSignal.timeout(4000) });
    if (!response.ok) throw Error('Local serial server unavailable');
    const info = await response.json();
    SerialConnection.receiverStatus = info;
    globalThis.dispatchEvent(new Event('receiverstatus'));
    return info;
  })().finally(() => { statusRequest = null; });
  const getPorts = async () => {
    const info = await refreshStatus();
    return info.connected && !info.busy ? [new BackendPort(info)] : [];
  };
  globalThis.SerialConnection = {
    backend: true, receiverStatus: null, supported: () => true, defaultKind: () => 'backend', kind: () => 'backend',
    getPorts,
    async requestPort() {
      const ports = await getPorts();
      if (!ports.length) throw Error('Searching for ESP-SDR. Plug in the receiver and close other serial applications.');
      return ports[0];
    },
    reconnect: port => port,
    onConnect(callback) {
      // Status refresh must not depend on the Connect handler being idle.
      const poll = async () => {
        if (globalThis.C3ScopeStopped) return;
        try {
          const info = await refreshStatus();
          if (info.connected && !info.busy) callback();
        } catch {
          SerialConnection.receiverStatus = { state: 'unavailable', message: 'The local server is unavailable. Retrying automatically…' };
          globalThis.dispatchEvent(new Event('receiverstatus'));
        } finally { setTimeout(poll, 1000); }
      };
      poll();
    },
  };
  document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('choosePort').hidden = true;
  });
})();
