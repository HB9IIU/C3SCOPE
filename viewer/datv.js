// Spectrum-only hints: no DVB demodulation or modulation/FEC identification.
(function (root) {
  'use strict';
  const percentile = (values, fraction) => {
    const sorted = Array.from(values).sort((a, b) => a - b);
    return sorted[Math.floor((sorted.length - 1) * fraction)];
  };
  const rates = [66, 125, 250, 333, 500, 1000, 1500, 2000];

  function detect(bins, { frequency, rate }, low = 2401e6, high = 2410e6) {
    if (!bins || bins.length < 128 || !Number.isFinite(frequency) || !(rate > 0)) return [];
    const step = rate / bins.length, start = frequency * 1e6 - rate / 2;
    const first = Math.max(2, Math.ceil((low - start) / step));
    const last = Math.min(bins.length - 3, Math.floor((high - start) / step));
    if (last - first < 32) return [];
    const smooth = [];
    for (let i = first; i <= last; i++) {
      // Median rejects isolated carrier spikes before width measurement.
      smooth.push(percentile([bins[i - 1], bins[i], bins[i + 1]], .5));
    }
    if (smooth.some(v => !Number.isFinite(v))) return [];
    const edgeCount = Math.max(8, Math.floor(smooth.length / 5));
    const leftNoise = percentile(smooth.slice(0, edgeCount), .2);
    const rightNoise = percentile(smooth.slice(-edgeCount), .2);
    const excess = smooth.map((value, i) => value - (leftNoise + (rightNoise - leftNoise) * i / (smooth.length - 1)));
    const results = [];
    for (let i = 1; i < excess.length - 1; i++) {
      if (excess[i] < 6) continue;
      const a = i;
      while (i < excess.length && excess[i] >= 6) i++;
      const b = i - 1;
      // Need both shoulders and enough independent bins to estimate a width.
      if (a <= 1 || b >= excess.length - 2 || b - a < 8) continue;
      const region = excess.slice(a, b + 1), top = percentile(region, .8);
      if (top < 10 || Math.max(...region) - top > 7) continue;
      // Remove the estimated noise power before measuring half-power edges.
      const halfPower = 10 * Math.log10(1 + (10 ** (top / 10) - 1) / 2);
      let l = a, r = b;
      while (l < b && excess[l] < halfPower) l++;
      while (r > a && excess[r] < halfPower) r--;
      if (r - l < 6) continue;
      const crossing = (x, y) => x + (halfPower - excess[x]) / (excess[y] - excess[x]) * (y - x);
      const left = crossing(l - 1, l), right = crossing(r, r + 1);
      const width = (right - left) * step;
      if (!Number.isFinite(width) || width < 50000 || width > 2400000) continue;
      // Judge the shoulders relative to the signal top, not the distant noise
      // floor. Receiver pedestals can join a valid plateau to a much wider
      // low-level region, which must not be treated as modulation bandwidth.
      const shoulderLevel = Math.max(6, top - 10);
      let shoulderL = l, shoulderR = r;
      while (shoulderL > 0 && excess[shoulderL] > shoulderLevel) shoulderL--;
      while (shoulderR < excess.length - 1 && excess[shoulderR] > shoulderLevel) shoulderR++;
      if (shoulderL === 0 || shoulderR === excess.length - 1 || (shoulderR - shoulderL) * step > width * 1.6) continue;
      const inner = excess.slice(Math.ceil(left + (right - left) * .25), Math.floor(right - (right - left) * .25) + 1);
      if (inner.length < 3 || percentile(inner, .9) - percentile(inner, .1) > 4) continue;
      // For an ideal raised-cosine power spectrum, -3 dB width approximates Rs.
      // ETSI TR 102 376, Figure 5 discussion; this remains a shape-based guess.
      const nearest = rates.reduce((a, b) => Math.abs(a * 1000 - width) < Math.abs(b * 1000 - width) ? a : b);
      const nominal = Math.abs(nearest * 1000 - width) <= Math.max(2 * step, width * .12) ? nearest : null;
      results.push({ center: start + (first + (left + right) / 2) * step,
        bandwidth: width, symbolRate: nominal ? nominal * 1000 : width, nominal: !!nominal });
    }
    return results.slice(0, 6);
  }

  class Tracker {
    constructor() { this.reset(); }
    reset() { this.tracks = []; this.last = null; this.key = ''; }
    update(bins, config, now) {
      const key = [config.frequency, config.rate, bins.length, config.gainMode, config.gain, config.bandwidth].join('/');
      if (key !== this.key || (this.last !== null && now - this.last > 1500)) this.reset();
      this.key = key;
      this.last = now;
      const candidates = detect(bins, config);
      const used = new Set();
      const previous = this.tracks;
      this.tracks = candidates.map(candidate => {
        const match = this.tracks.find(t => !used.has(t) && Math.abs(t.center - candidate.center) < Math.max(30000, candidate.bandwidth * .2) && Math.abs(t.bandwidth - candidate.bandwidth) < candidate.bandwidth * .3);
        if (match) used.add(match);
        return { ...candidate,
          center: match ? .75 * match.center + .25 * candidate.center : candidate.center,
          since: match?.since ?? now, lastSeen: now, count: (match?.count ?? 0) + 1 };
      });
      // A single noisy spectrum must not erase a stable candidate. The short
      // grace period is bounded: vanished signals expire within 400 ms.
      for (const old of previous) if (!used.has(old) && now - old.lastSeen <= 400) this.tracks.push(old);
      return this.tracks.filter(t => now - t.since >= 1000 && t.count >= 5);
    }
  }
  function markers(signals, config, view, width) {
    const span = (view.b - view.a) * config.rate;
    if (!(span > 0) || !(width > 0)) return [];
    const start = config.frequency * 1e6 + (view.a - .5) * config.rate;
    return signals.map((signal, i) => ({ ...signal, id: i + 1,
      x: (signal.center - start) / span * width,
      left: (signal.center - signal.bandwidth / 2 - start) / span * width,
      right: (signal.center + signal.bandwidth / 2 - start) / span * width,
    })).filter(marker => marker.x >= 0 && marker.x <= width);
  }
  root.DatvDetection = { detect, Tracker, markers };

  if (!root.document) return;
  const tracker = new Tracker();
  let lastUpdate = -Infinity, lastFrame = -Infinity, active = false, paused = false;
  let confirmed = [], detectionConfig = null;
  const clearMarkers = () => { confirmed = []; detectionConfig = null; };
  const text = message => {
    const element = document.getElementById('datvStatus');
    if (element && element.textContent !== message) element.textContent = message;
  };
  root.DatvHints = {
    reset() { tracker.reset(); clearMarkers(); lastUpdate = -Infinity; lastFrame = -Infinity; text('Looking for persistent DATV-like signals…'); },
    state(connected, isPaused) {
      active = connected; paused = isPaused;
      if (!connected || isPaused) {
        tracker.reset();
        clearMarkers();
        text(connected ? 'Detection paused.' : 'Waiting for receiver.');
      }
    },
    update(bins, config) {
      const now = performance.now();
      lastFrame = now;
      if (now - lastUpdate < 150) return;
      lastUpdate = now;
      if (config.maxHold) { tracker.reset(); clearMarkers(); text('Use the AVG detector for DATV hints.'); return; }
      const signals = tracker.update(bins, config, now);
      confirmed = signals;
      detectionConfig = { frequency: config.frequency, rate: config.rate };
      text(signals.length ? signals.map(s => `Probable DATV TX at ${(s.center / 1e6).toFixed(3)} MHz · estimated SR ≈ ${Math.round(s.symbolRate / 1000)} kS/s`).join('\n') : 'Looking for persistent DATV-like signals…');
    },
    draw(ctx, config, view, width, height, d = 1) {
      if (!confirmed.length || performance.now() - lastFrame > 2000 ||
          config.frequency !== detectionConfig?.frequency || config.rate !== detectionConfig?.rate) return;
      const layout = markers(confirmed, config, view, width);
      const lanes = [-Infinity, -Infinity, -Infinity];
      ctx.save();
      ctx.beginPath(); ctx.rect(0, 0, width, height); ctx.clip();
      ctx.font = `${13 * d}px Menlo,Consolas,monospace`;
      ctx.textBaseline = 'top'; ctx.lineWidth = d;
      for (const mark of layout) {
        const label = `D${mark.id} DATV? · ${(mark.center / 1e6).toFixed(3)} MHz · SR ≈ ${Math.round(mark.symbolRate / 1000)} kS/s`;
        const labelWidth = Math.min(width, ctx.measureText(label).width + 12 * d);
        const labelX = Math.max(0, Math.min(width - labelWidth, mark.x - labelWidth / 2));
        const lane = lanes.findIndex(end => labelX > end + 8 * d);
        const y = (lane >= 0 ? 32 + lane * 26 : 32) * d;
        if (lane >= 0) {
          lanes[lane] = labelX + labelWidth;
          ctx.fillStyle = '#07151df0'; ctx.fillRect(labelX, y - 24 * d, labelWidth, 21 * d);
          ctx.fillStyle = '#8de1ff'; ctx.fillText(label, labelX + 6 * d, y - 22 * d, labelWidth - 12 * d);
        }
        ctx.strokeStyle = '#72d8ffc0'; ctx.setLineDash([]);
        ctx.beginPath(); ctx.moveTo(Math.max(0, mark.left), y); ctx.lineTo(Math.min(width, mark.right), y);
        if (mark.left >= 0) { ctx.moveTo(mark.left, y - 4 * d); ctx.lineTo(mark.left, y + 5 * d); }
        if (mark.right <= width) { ctx.moveTo(mark.right, y - 4 * d); ctx.lineTo(mark.right, y + 5 * d); }
        ctx.stroke();
        ctx.fillStyle = '#72d8ff'; ctx.beginPath();
        ctx.moveTo(mark.x - 4 * d, y + 3 * d); ctx.lineTo(mark.x + 4 * d, y + 3 * d); ctx.lineTo(mark.x, y + 9 * d); ctx.fill();
        ctx.strokeStyle = '#72d8ff55'; ctx.setLineDash([3 * d, 5 * d]);
        ctx.beginPath(); ctx.moveTo(mark.x, y + 10 * d); ctx.lineTo(mark.x, height); ctx.stroke();
      }
      ctx.restore();
    },
  };
  setInterval(() => {
    if (active && !paused && performance.now() - lastFrame > 2000) {
      tracker.reset();
      clearMarkers();
      text('Waiting for fresh spectrum data…');
    }
  }, 500);
})(globalThis);
