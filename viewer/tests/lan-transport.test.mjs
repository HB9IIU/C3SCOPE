import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFile } from 'node:fs/promises';
const source = await readFile(new URL('../radio.js', import.meta.url), 'utf8');
function fixture(backend) {
  const ctx = vm.createContext({ isSecureContext: false, SerialConnection: { backend } });
  vm.runInContext(source, ctx);
  const radio = vm.runInContext('radio', ctx);
  radio.run = async fn => fn();
  radio.close = async () => {};
  radio.connectPort = async () => {};
  radio.negotiate = async () => 'connected';
  return radio;
}
test('Python serial backend works over HTTP LAN without browser USB permissions', async () => {
  assert.equal(await fixture(true).connect({ port: {} }), 'connected');
});
test('direct browser USB still requires a secure context', async () => {
  await assert.rejects(fixture(false).connect({ port: {} }), /HTTPS or localhost/);
});
