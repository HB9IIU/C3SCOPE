# Baseline inspection — 26 October 2026

## Provenance

- Frontend: https://github.com/ESPARGOS/esp-web-sdr
  revision `6995ed78915a034be54be68abf986d608d7624c4`.
- Firmware reference: https://github.com/ESPARGOS/esp-sdr
  revision `9b61e7465bee6da15209c5c09308043d08c46a1d`.
  Inspected in `/tmp/qo100-esp-sdr-reference`; not bundled or flashed.
- Frontend LICENSE and README inspected: GPL-3.0-or-later, with separate
  third-party notices in `flasher/vendor/` and `fonts.css`, retained unchanged.
- Workspace initially contained only the supplied brief and `.DS_Store`.
  No applicable AGENTS.md was found in the workspace or inspected ancestors.

## Architecture and protocol findings

Retain direct browser USB: `serial-transport.js` provides the transport,
`radio.js` negotiates and parses the protocol, and `app.js` handles display
and controls. A localhost static server does not own the receiver.

Inspected firmware `docs/protocol.md`, `docs/spectrum.md`, the C3 receiver
command implementation, and frontend negotiation/decoder/stream code.

- Commands are newline-terminated ASCII. Session synchronization uses a
  nonce; `INFO` and `CAPS` identify the receiver and available commands.
  Optional `VERSION?`, `LIMITS?`, `TRANSPORT?`, and `SPECINFO?` queries are
  capability gated. The installed device revision remains unknown.
- The current C3 implementation advertises spectrum sizes/rates through
  `SPECINFO?`. Its documented snapshot profiles cover 256–2048 bins at
  16/40/80 MS/s. Rate codes are 6/1/0 respectively. Do not infer support
  solely from a chip name; frontend validates the advertised profiles.
- Tune commands use whole MHz; returned spectrum sample rates use Hz and
  the frontend converts the returned LO from MHz to Hz. Gain indices are
  PHY table entries, not gain in dB. Limits and AGC support are negotiated.
- The frontend serializes operations, tunes and sets gain before starting
  `SPEC`. Ordinary commands must wait for the stream to end. A newline
  requests stop; an unconfirmed end boundary makes the connection unusable
  until reconnect, rather than allowing commands into an uncertain stream.
- `SPEC` replies with FFT size, sample rate, capture-unit size and LO MHz.
  `SPC1` binary frames contain a 28-byte header, N power bytes, and a
  little-endian CRC32 over header plus bins. Header metadata includes frame
  sequence, sample index, span, FFT count, flags, gain and dropped frames.
  The frontend validates FFT size, encoding multiplier, and CRC, and
  resynchronizes after corruption. Partial serial reads are supported.
- Power bytes arrive in natural FFT order, with encoding multiplier 2;
  upstream applies Hann normalization for relative dBFS. Preserve its
  decoding and FFT orientation. Quantized zero is a floor, not absent RF.
- Optional `SPS1` statistics have a 36-byte body plus CRC. `SPECEND` has
  twelve numeric fields. Upstream provides CRC/drop reporting and bounded
  transport buffering; new UI should expose these without inventing rates.
- Snapshot sample indices use elapsed wall time according to the firmware
  protocol documentation. They are not evidence of continuous acquisition.
- Firmware DC correction and display filling can affect signals near LO;
  keep these explicit and preserve upstream behavior for the baseline.

Compatibility is capability based, not a claim that every firmware revision
works. The current frontend includes legacy fallbacks, especially for S3;
the actual C3 must be queried before promising its available controls.

## Validation results

- Unchanged frontend: `node --test viewer/tests/*.test.mjs` — **176 passed,
  0 failed**, including fragmented binary frames, CRC recovery, C3 settings,
  stream recovery, gain, and serial transport tests.
- Local static server started on 127.0.0.1:8000. HTTP GET/HEAD availability
  checked with HEAD: **200 OK**, HTML content type.
- Git working tree in `viewer/` remained clean after baseline testing.
- Browser visual/interaction validation: **not performed**. Neither Chrome
  nor the in-app browser was available through session browser automation.
- Hardware: **not connected or tested by this agent**. The user's reported
  prior success establishes their upstream receiver chain, not validation
  of this checkout. No measured frame rate, latency, sensitivity, RF-axis
  orientation, gain response, or prolonged stability result is claimed.

## First implementation slice

Keep transport and firmware unchanged. Add a capability-checked QO-100
preset (2406 MHz, nominal 16 MS/s, 2048 bins where advertised), then derive
the 2401–2410 MHz view fractions from the received LO and sample rate.
Use one mapping for spectrum, waterfall and cursor; add a Reset QO-100
view action. Preserve gain, pause and disconnect behavior. Add explicit
local-uplink branding and visible upstream credit.

Validate exact crop boundaries and frequency translation with synthetic
frames, then inspect rendering in an available browser. Real hardware
acceptance still requires the already-flashed C3, signal movement checks,
edge coverage and disconnect/reconnect tests. Do not add detailed bandplan
allocations until checking the current primary source.
