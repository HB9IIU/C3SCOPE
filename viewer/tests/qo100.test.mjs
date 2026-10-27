import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFile } from 'node:fs/promises';
import { statement } from './source.mjs';
const app = await readFile(new URL('../app.js', import.meta.url), 'utf8');

function qoView() {
  const c = vm.createContext({});
  vm.runInContext(statement(app, 'function qoView(c)'), c);
  return c.qoView;
}
// Frequency in Hz at view fraction x, as the plots map it: LO - rate/2 + x * rate.
const at = (c, x) => c.frequency * 1e6 - c.rate / 2 + x * c.rate;

for (const [lo, rate, a, b] of [
  [2406, 16000000, 3 / 16, 12 / 16],
  [2412, 80000000, 29 / 80, 38 / 80],
  [2405, 20000000, 6 / 20, 15 / 20],
])
  test(`QO-100 view at ${lo} MHz, ${rate / 1e6} MS/s ends exactly at 2401 and 2410 MHz`, () => {
    const c = { frequency: lo, rate };
    const v = qoView()(c);
    assert.equal(v.a, a);
    assert.equal(v.b, b);
    assert.equal(at(c, v.a), 2401000000);
    assert.equal(at(c, v.b), 2410000000);
  });

test('QO-100 view is clipped to the received span', () => {
  assert.deepEqual({ ...qoView()({ frequency: 2412, rate: 16000000 }) }, { a: 0, b: 6 / 16 });
  assert.deepEqual({ ...qoView()({ frequency: 2400, rate: 4000000 }) }, { a: 0.75, b: 1 });
});

test('QO-100 view falls back to the full span when the window is not received', () => {
  assert.deepEqual({ ...qoView()({ frequency: 2442, rate: 16000000 }) }, { a: 0, b: 1 });
  assert.deepEqual({ ...qoView()({ frequency: 5500, rate: 80000000 }) }, { a: 0, b: 1 });
});

function preset({ valid = true, stream = true, sizes = [256, 512, 1024, 2048] } = {}) {
  const inputs = { frequency: { value: '2412' }, rate: { value: '80000000' }, fft: { value: '256' } };
  const c = vm.createContext({
    $: (id) => inputs[id],
    radio: {
      canStreamSpectrum: stream,
      validFrequency: (f) => valid && f === 2406,
      spectrumProfiles: (rate) => (rate === 16000000 ? sizes.map((n) => [rate, 0, n, 1, 1]) : []),
    },
  });
  vm.runInContext(
    'let tuneFrequency = 2412, spectrumMode = false;' + statement(app, 'function qoPreset()'),
    c,
  );
  const problem = c.qoPreset();
  return {
    problem,
    inputs,
    ...vm.runInContext('({ tuneFrequency, spectrumMode })', c),
  };
}

test('QO-100 preset selects 2406 MHz, 16 MS/s, 2048-bin on-chip spectra', () => {
  const r = preset();
  assert.equal(r.problem, '');
  assert.equal(r.tuneFrequency, 2406);
  assert.equal(r.spectrumMode, true);
  assert.equal(r.inputs.frequency.value, '2406');
  assert.equal(r.inputs.rate.value, '16000000');
  assert.equal(r.inputs.fft.value, '2048');
});

test('QO-100 preset uses the largest advertised FFT size without 2048 bins', () => {
  assert.equal(preset({ sizes: [256, 1024, 512] }).inputs.fft.value, '1024');
});

for (const [name, options] of [
  ['2406 MHz is not tunable', { valid: false }],
  ['spectra cannot be streamed', { stream: false }],
  ['16 MS/s spectra are not advertised', { sizes: [] }],
])
  test(`QO-100 preset leaves settings unchanged when ${name}`, () => {
    const r = preset(options);
    assert.match(r.problem, /firmware/);
    assert.equal(r.tuneFrequency, 2412);
    assert.equal(r.spectrumMode, false);
    assert.deepEqual(
      [r.inputs.frequency.value, r.inputs.rate.value, r.inputs.fft.value],
      ['2412', '80000000', '256'],
    );
  });

function channels(c, W = 900) {
  const bars = [];
  const g = {
    fillRect() {},
    beginPath() {},
    fill() {},
    fillText() {},
    measureText: (s) => ({ width: s.length * 6 }),
    createLinearGradient: () => ({ addColorStop() {} }),
    roundRect: (x, y, w) => bars.push({ x: x + w / 2, y, w }),
  };
  const el = { clientWidth: W, clientHeight: 34, getContext: () => g };
  const ctx = vm.createContext({ $: () => el, devicePixelRatio: 1 });
  vm.runInContext(
    'let view;' +
      statement(app, 'function qoView(c)') +
      statement(app, 'const SCREEN =') +
      statement(app, 'function axisTicks(c, W)') +
      statement(app, 'const QO_CHANNELS =') +
      statement(app, 'function drawChannels(c)') +
      'view = qoView(' + JSON.stringify(c) + ');',
    ctx,
  );
  ctx.drawChannels(c);
  return { bars, rows: vm.runInContext('QO_CHANNELS', ctx) };
}

test('channel rows hold the bandplan V3 uplink centres', () => {
  const { rows } = channels({ frequency: 2406, rate: 16000000 });
  const centres = rows.map((r) => {
    const out = [];
    for (let f = r.first; f <= r.last; f += r.step) out.push(f / 1e6);
    return out;
  });
  assert.equal(centres[0].length, 27);
  assert.deepEqual([centres[0][0], centres[0][1], centres[0].at(-1)], [2403.25, 2403.5, 2409.75]);
  assert.equal(centres[1].length, 14);
  assert.deepEqual([centres[1][0], centres[1][1], centres[1].at(-1)], [2403.25, 2403.75, 2409.75]);
  assert.deepEqual(centres[2], [2403.75, 2405.25, 2406.75]);
});

test('channel bars are centred where the cropped view places their frequency', () => {
  const W = 900,
    { bars } = channels({ frequency: 2406, rate: 16000000 }, W);
  assert.equal(bars.length, 27 + 14 + 3);
  const wide = bars.slice(-3).map((b) => b.x);
  // Cropped view spans 2401-2410 MHz across W pixels: 100 px per MHz.
  for (const [i, mhz] of [2403.75, 2405.25, 2406.75].entries())
    assert.ok(Math.abs(wide[i] - (mhz - 2401) * (W / 9)) < 1e-6);
  assert.ok(bars.every((b) => b.w > 0));
});

test('zoom and pan stay inside the 2401-2410 MHz window', () => {
  const ctx = vm.createContext({
    latest: { frequency: 2406, rate: 16000000, fft: 2048 },
    redrawWater() {},
    draw() {},
    labels() {},
  });
  vm.runInContext(
    'let view;' + statement(app, 'function qoView(c)') + statement(app, 'function setView(a, b)'),
    ctx,
  );
  const view = (a, b) => {
    ctx.setView(a, b);
    return vm.runInContext('view', ctx);
  };
  const q = { a: 3 / 16, b: 12 / 16 };
  // Zooming out or asking for the whole received span gives exactly the window.
  assert.deepEqual({ ...view(-1, 2) }, q);
  assert.deepEqual({ ...view(0, 1) }, q);
  // A zoomed view dragged past either edge stops at that edge, keeping its width.
  let v = view(-0.5, -0.4);
  assert.equal(v.a, q.a);
  assert.ok(Math.abs(v.b - v.a - 0.1) < 1e-12);
  v = view(1.2, 1.3);
  assert.equal(v.b, q.b);
  assert.ok(Math.abs(v.b - v.a - 0.1) < 1e-12);
  // Zooming in inside the window is unchanged.
  assert.deepEqual({ ...view(0.4, 0.5) }, { a: 0.4, b: 0.5 });
  // Closer than 1 MHz (1/16 of 16 MS/s) stops at 1 MHz around the requested centre.
  v = view(0.45, 0.452);
  assert.ok(Math.abs(v.b - v.a - 1 / 16) < 1e-12);
  assert.ok(Math.abs((v.a + v.b) / 2 - 0.451) < 1e-12);
  // ...and still inside the window at its edge.
  v = view(q.a, q.a + 0.001);
  assert.equal(v.a, q.a);
  assert.ok(Math.abs(v.b - v.a - 1 / 16) < 1e-12);
});

test('axis labels never overlap and keep both window ends', () => {
  const texts = [];
  const g = {
    fillRect() {},
    beginPath() {},
    moveTo() {},
    lineTo() {},
    closePath() {},
    stroke() {},
    fill() {},
    measureText: (s) => ({ width: s.length * 7 }),
    fillText: (s, x) => texts.push({ s, x, w: s.length * 7 }),
  };
  const el = { clientWidth: 1466, clientHeight: 32, getContext: () => g };
  const c = { frequency: 2406, rate: 16000000 };
  const ctx = vm.createContext({ $: () => el, devicePixelRatio: 1, tuneFrequency: 2406 });
  vm.runInContext(
    'let view;' +
      statement(app, 'function qoView(c)') +
      statement(app, 'const SCREEN =') +
      statement(app, 'function axisTicks(c, W)') +
      statement(app, 'function drawAxis(c)') +
      'view = qoView(' + JSON.stringify(c) + ');',
    ctx,
  );
  ctx.drawAxis(c);
  const labels = texts.map((t) => t.s);
  assert.ok(labels.includes('2401.0') && labels.includes('2410.0'));
  texts.sort((p, q) => p.x - q.x);
  for (let i = 1; i < texts.length; i++) assert.ok(texts[i].x >= texts[i - 1].x + texts[i - 1].w, labels.join(' '));
});
