import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFile } from 'node:fs/promises';
const ctx = vm.createContext({});
vm.runInContext(await readFile(new URL('../datv.js', import.meta.url), 'utf8'), ctx);
const { detect, Tracker } = ctx.DatvDetection;
test('markers map RF centers and measured widths correctly through zoom and pan', () => {
  const signal = { center: 2405e6, bandwidth: 500e3, symbolRate: 500e3 };
  const full = ctx.DatvDetection.markers([signal], { frequency: 2406, rate: 16e6 }, { a: 0, b: 1 }, 1600)[0];
  assert.equal(full.x, 700);
  assert.equal(full.left, 675);
  assert.equal(full.right, 725);
  const zoom = ctx.DatvDetection.markers([signal], { frequency: 2406, rate: 16e6 }, { a: .4, b: .5 }, 1600)[0];
  assert.ok(Math.abs(zoom.x - 600) < 1e-6);
  assert.ok(Math.abs(zoom.right - zoom.left - 500) < 1e-6);
  assert.equal(ctx.DatvDetection.markers([signal], { frequency: 2406, rate: 16e6 }, { a: .6, b: .8 }, 1600).length, 0);
});
const config = { frequency: 2406, rate: 16000000 };
function spectrum(signals = [], n = 2048, slope = 0) {
  let seed = 42;
  return Array.from({ length: n }, (_, i) => {
    seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0;
    const noiseDb = -65 + slope * (i / n - .5);
    let power = 10 ** (noiseDb / 10);
    const hz = config.frequency * 1e6 + (i / n - .5) * config.rate;
    for (const signal of signals) {
      const d = Math.abs(hz - signal.center), alpha = signal.rolloff ?? .25;
      const flat = signal.sr * (1 - alpha) / 2, edge = signal.sr * (1 + alpha) / 2;
      const shape = d <= flat ? 1 : d >= edge ? 0 : (1 + Math.cos(Math.PI * (d - flat) / (edge - flat))) / 2;
      power += shape * 10 ** ((noiseDb + (signal.snr ?? 22)) / 10);
    }
    return 10 * Math.log10(power) + ((seed / 2 ** 32) - .5) * 1.5;
  });
}
test('rejects noise, narrow carriers and signals cut off at the display boundary', () => {
  assert.equal(detect(spectrum(), config).length, 0);
  const tone = spectrum(); tone[1000] = -10; tone[1001] = -15;
  assert.equal(detect(tone, config).length, 0);
  assert.equal(detect(spectrum([{ center: 2401e6, sr: 500e3 }]), config).length, 0);
});
test('estimates center and SR for raised-cosine DATV shapes at different rolloffs', () => {
  for (const sr of [125e3, 250e3, 333e3, 500e3, 1000e3, 2000e3]) {
    for (const rolloff of [.2, .25, .35]) {
      const signals = detect(spectrum([{ center: 2405.75e6, sr, rolloff }], 2048, 6), config);
      assert.equal(signals.length, 1, `SR ${sr}, rolloff ${rolloff}`);
      assert.ok(Math.abs(signals[0].center - 2405.75e6) < 16000);
      assert.ok(Math.abs(signals[0].symbolRate - sr) < sr * .15);
    }
  }
});
test('separates two signals and does not mistake a broad sloping noise hump for DATV', () => {
  const candidates = detect(spectrum([{ center: 2403e6, sr: 250e3 }, { center: 2407e6, sr: 500e3 }]), config);
  assert.equal(candidates.length, 2);
  const hump = spectrum().map((v, i) => v + 18 * Math.exp(-(((i - 1000) / 220) ** 2)));
  assert.equal(detect(hump, config).length, 0);
});
test('requires persistence and clears old detections after disappearance, retune or data gap', () => {
  const tracker = new Tracker(), bins = spectrum([{ center: 2405.75e6, sr: 500e3 }]);
  for (let t = 0; t < 1000; t += 200) assert.equal(tracker.update(bins, config, t).length, 0);
  assert.equal(tracker.update(bins, config, 1000).length, 1);
  assert.equal(tracker.update(spectrum(), config, 1200).length, 1);
  assert.equal(tracker.update(spectrum(), config, 1600).length, 0);
  for (let t = 1800; t <= 2800; t += 200) tracker.update(bins, config, t);
  assert.equal(tracker.update(bins, { ...config, frequency: 2407 }, 3000).length, 0);
  assert.equal(tracker.update(bins, config, 5000).length, 0);
});

test('one missed spectrum does not prevent confirmation of a persistent signal', () => {
  const tracker = new Tracker(), bins = spectrum([{ center: 2405.25e6, sr: 500e3 }]);
  for (let t = 0; t < 1000; t += 150) tracker.update(t === 450 ? spectrum() : bins, config, t);
  assert.equal(tracker.update(bins, config, 1050).length, 1);
});

test('finds a flat DATV plateau over broad raised shoulders like the receiver screenshot', () => {
  const bins = spectrum([{ center: 2405.25e6, sr: 500e3, snr: 35 }]);
  for (let i = 0; i < bins.length; i++) {
    const hz = config.frequency * 1e6 + (i / bins.length - .5) * config.rate;
    // A 9 dB pedestal extends well past the true modulation edges.
    const pedestal = 9 * Math.exp(-(((hz - 2405.25e6) / 700000) ** 8));
    bins[i] = 10 * Math.log10(10 ** (bins[i] / 10) + 10 ** ((-65 + pedestal) / 10));
  }
  const signals = detect(bins, config);
  assert.equal(signals.length, 1);
  assert.ok(Math.abs(signals[0].center - 2405.25e6) < 16000);
  assert.ok(Math.abs(signals[0].symbolRate - 500e3) < 75000);
});
