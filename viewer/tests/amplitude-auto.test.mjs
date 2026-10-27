import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFile } from 'node:fs/promises';
const source = await readFile(new URL('../app.js', import.meta.url), 'utf8');
function fixture(floorOn, scaleOn) {
  const elements = {
    autofloor: { checked: floorOn }, autoscale: { checked: scaleOn },
    floor: { value: '-100' }, range: { value: '80' },
    floorValue: {}, rangeValue: {}, scale: {},
  };
  let time = 0;
  const ctx = vm.createContext({ $: id => elements[id], view: { a: .25, b: .75 },
    performance: { now: () => time }, autoT: -Infinity, autoPk: null,
    redrawWater() {}, draw() {},
  });
  vm.runInContext(source.slice(source.indexOf('function autoScale(values)'), source.indexOf("$('autoscale').onchange")), ctx);
  return { elements, update: values => { time += 1100; ctx.autoScale(values); } };
}
const bins = () => Array.from({ length: 200 }, (_, i) => i < 50 || i >= 150 ? -5 : i >= 95 && i < 105 ? -40 : -80);
test('auto floor alone follows visible noise smoothly and preserves range', () => {
  const { elements: e, update } = fixture(true, false);
  update(bins());
  assert.equal(Number(e.floor.value), -97);
  assert.equal(Number(e.range.value), 80);
  for (let i = 0; i < 12; i++) update(bins());
  assert.ok(Math.abs(Number(e.floor.value) - -85) <= 2);
});
test('auto scale alone preserves manual floor and ignores offscreen peaks', () => {
  const { elements: e, update } = fixture(false, true);
  update(bins());
  assert.equal(Number(e.floor.value), -100);
  assert.equal(Number(e.floor.value) + Number(e.range.value), -37);
});
test('both automatic controls cooperate and both off preserves manual limits', () => {
  const both = fixture(true, true);
  both.update(bins());
  assert.equal(Number(both.elements.floor.value), -97);
  assert.equal(Number(both.elements.floor.value) + Number(both.elements.range.value), -37);
  const manual = fixture(false, false);
  manual.update(bins());
  assert.equal(Number(manual.elements.floor.value), -100);
  assert.equal(Number(manual.elements.range.value), 80);
});

test('range settles close to a weaker signal instead of leaving large empty headroom', () => {
  const { elements: e, update } = fixture(false, true);
  update(bins());
  const weaker = bins().map((v, i) => i >= 95 && i < 105 ? -55 : v);
  update(weaker);
  update(weaker);
  const firstTop = Number(e.floor.value) + Number(e.range.value);
  assert.ok(firstTop >= -40 && firstTop < -37, 'gradual downward movement after dead band');
  for (let i = 0; i < 15; i++) update(weaker);
  const settled = Number(e.floor.value) + Number(e.range.value);
  assert.ok(settled >= -52 && settled <= -50, `settled top ${settled}`);
  const stronger = bins().map((v, i) => i >= 95 && i < 105 ? -25 : v);
  update(stronger);
  assert.equal(Number(e.floor.value) + Number(e.range.value), -22);
});
