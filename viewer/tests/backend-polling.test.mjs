import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFile } from 'node:fs/promises';

const source = await readFile(new URL('../backend-transport.js', import.meta.url), 'utf8');
test('polling updates an open page as devices arrive and recovers from request failure', async () => {
  let info = { connected: false, state: 'searching' }, failure = false, connects = 0, updates = 0;
  const timers = [];
  const ctx = vm.createContext({
    document: { addEventListener() {} }, Event, AbortSignal,
    dispatchEvent: () => updates++,
    setTimeout: fn => timers.push(fn),
    fetch: async () => {
      if (failure) throw Error('temporary failure');
      return { ok: true, json: async () => info };
    },
  });
  vm.runInContext(source, ctx);
  const settle = () => new Promise(resolve => setImmediate(resolve));
  ctx.SerialConnection.onConnect(() => connects++);
  await settle();
  assert.equal(ctx.SerialConnection.receiverStatus.state, 'searching');
  info = { connected: false, state: 'incompatible' };
  await timers.shift()();
  assert.equal(ctx.SerialConnection.receiverStatus.state, 'incompatible');
  assert.equal(connects, 0);
  failure = true;
  await timers.shift()();
  assert.equal(ctx.SerialConnection.receiverStatus.state, 'unavailable');
  failure = false;
  info = { connected: true, busy: false, state: 'ready' };
  await timers.shift()();
  assert.equal(connects, 1);
  assert.equal(updates, 4);
});
