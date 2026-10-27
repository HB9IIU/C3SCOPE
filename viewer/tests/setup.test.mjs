import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFile } from 'node:fs/promises';
const source = await readFile(new URL('../setup.js', import.meta.url), 'utf8');
function fixture(kind = 'c3cast') {
  const elements = new Map(), events = new Map(), calls = [], handoffs = [];
  class Element {
    constructor() { this.children = []; this.checked = false; this.disabled = false; this.hidden = false; this.listeners = {}; }
    set innerHTML(html) { for (const match of html.matchAll(/id="([^"]+)"/g)) elements.set(match[1], new Element()); }
    setAttribute() {} removeAttribute() {} focus() {}
    append(...items) { this.children.push(...items); }
    replaceChildren(...items) { this.children = items; }
    addEventListener(name, callback) { this.listeners[name] = callback; }
    showModal() { this.open = true; } close() { this.open = false; }
  }
  const get = id => { if (!elements.has(id)) elements.set(id, new Element()); return elements.get(id); };
  const ctx = vm.createContext({
    document: { getElementById: get, createElement: () => new Element(),
      body: { append() {}, classList: { contains: () => true } } },
    SerialConnection: { backend: true, receiverStatus: { installation: { state: 'idle' },
      device: 'COM_TEST', can_reinstall: kind === 'receiver',
      setup_candidates: kind === 'receiver' ? [] : [{ device: 'COM_TEST', kind, fingerprint: ['COM_TEST', 'test-mac'] }] } },
    C3ScopeFirmware: { releaseReceiver: async () => handoffs.push('release'), resume: () => handoffs.push('resume') },
    addEventListener: (name, callback) => events.set(name, callback),
    AbortSignal,
    fetch: async (url, options) => {
      calls.push({ url, data: JSON.parse(options.body) });
      if (url.endsWith('install')) handoffs.push('install-request');
      return { ok: true, json: async () => url.endsWith('prepare') ?
        { token: 'review-token', device: 'COM_TEST', kind, board: 'Seeed Studio XIAO ESP32-C3', build_date: '2026-10-17' } : { started: true, job_id: 'new-install' } };
    },
  });
  vm.runInContext(source, ctx);
  return { get, calls, ctx, events, handoffs, convert: () => get('setupDevices').children[0].children[2].children[1] };
}
test('C3CAST conversion requires review and both unchecked confirmations', async () => {
  const f = fixture();
  assert.match(f.get('receiverWaitingTitle').textContent, /C3CAST/);
  assert.equal(f.calls.length, 0);
  await f.convert().onclick();
  assert.equal(f.calls.length, 1);
  assert.equal(f.get('setupC3castWarning').hidden, false);
  assert.equal(f.get('setupConfirmBoard').checked, false);
  assert.equal(f.get('setupInstall').disabled, true);
  await f.get('setupInstall').onclick();
  assert.equal(f.calls.length, 1);
  f.get('setupConfirmBoard').checked = true;
  f.get('setupConfirmBoard').onchange();
  assert.equal(f.get('setupInstall').disabled, true);
  f.get('setupConfirmErase').checked = true;
  f.get('setupConfirmErase').onchange();
  assert.equal(f.get('setupInstall').disabled, false);
  await f.get('setupInstall').onclick();
  assert.deepEqual(f.calls[1], { url: '/api/setup/install', data: { token: 'review-token', confirm_board: true, confirm_erase: true } });
});
test('cancelling review and keeping C3CAST never sends an install request', async () => {
  const f = fixture();
  await f.convert().onclick();
  f.get('setupCancel').onclick();
  await f.get('setupInstall').onclick();
  assert.equal(f.calls.length, 1);
  f.get('setupDevices').children[0].children[2].children[0].onclick();
  assert.equal(f.get('setupDevices').children.length, 0);
  assert.equal(f.calls.filter(c => c.url.endsWith('install')).length, 0);
});
test('unrecognized firmware is offered setup without claiming it is a transmitter', async () => {
  const f = fixture('unknown');
  await f.convert().onclick();
  assert.equal(f.get('setupC3castWarning').hidden, true);
  assert.match(f.get('setupConfirmTitle').textContent, /XIAO/);
});

test('receiver reinstall review can be cancelled without stopping acquisition', async () => {
  const f = fixture('receiver');
  await f.get('reinstallFirmware').onclick();
  assert.equal(f.calls[0].data.operation, 'reinstall');
  assert.equal(f.get('setupConfirmTitle').textContent, 'Reinstall receiver firmware?');
  f.get('setupCancel').onclick();
  assert.equal(f.handoffs.length, 0);
  assert.equal(f.calls.length, 1);
});

test('erase has a distinct blank-board warning and cancellation does not release or erase', async () => {
  const f = fixture('receiver');
  await f.get('eraseReceiver').onclick();
  assert.equal(f.calls[0].data.operation, 'erase');
  assert.equal(f.get('setupConfirmTitle').textContent, 'Erase this ESP32 completely?');
  assert.match(f.get('setupOperationDescription').textContent, /blank/);
  assert.match(f.get('setupEraseLabel').textContent, /No replacement firmware/);
  assert.equal(f.get('setupInstall').textContent, 'Erase ESP32');
  assert.equal(f.get('setupInstall').disabled, true);
  f.get('setupCancel').onclick();
  assert.equal(f.handoffs.length, 0);
  assert.equal(f.calls.length, 1);
});

test('receiver update releases serial only after confirmation and reconnects after its own job', async () => {
  const f = fixture('receiver');
  await f.get('updateFirmware').onclick({ preventDefault() {} });
  assert.equal(f.calls[0].data.operation, 'update');
  assert.equal(f.handoffs.length, 0);
  f.get('setupConfirmBoard').checked = true;
  f.get('setupConfirmErase').checked = true;
  f.get('setupConfirmErase').onchange();
  await f.get('setupInstall').onclick();
  assert.deepEqual(f.handoffs, ['release', 'install-request']);
  f.ctx.SerialConnection.receiverStatus.installation = { id: 'old-install', state: 'complete' };
  f.events.get('receiverstatus')();
  assert.equal(f.handoffs.includes('resume'), false);
  f.ctx.SerialConnection.receiverStatus.installation = { id: 'new-install', state: 'complete' };
  f.events.get('receiverstatus')();
  assert.equal(f.handoffs.at(-1), 'resume');
});
