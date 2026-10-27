# C3SCOPE

**See your signal.** A local QO-100 DATV uplink spectrum viewer by HB9IIU,
part of the C3 family alongside [C3CAST](https://github.com/HB9IIU/C3CAST).
Startup uses Manual RX gain at index 0 (clamped to the receiver's supported
limits), with Auto Scale and Auto Floor enabled. Auto Floor follows the visible
noise about 5 dB below its lower percentile; Auto Scale follows the visible
peak. They adjust display levels only. Moving the Floor or Range slider turns
off its corresponding automatic control.
`viewer/` is ESP-WebSDR with QO-100 changes on its local `qo100` branch;
upstream `main` is left untouched at the recorded baseline commit.

## Run locally

From this directory:

```sh
python -m pip install -r requirements.txt
python app.py
```

C3SCOPE automatically opens http://127.0.0.1:8000 in your default browser.
If port 8000 is occupied, it uses the first available port up to 8019 and opens
that address instead. The selected URL is also printed in the terminal.
If the browser does not open, use that URL manually. Connect the already-flashed
XIAO ESP32-C3 with a USB data cable and close any serial monitor using it.
The Flask server enumerates COM ports at startup and every half second,
probes USB serial ports with SYNC and INFO, and connects the first confirmed
ESP-SDR. USB ports are probed independently so an unrelated silent device
does not hold up a newly connected receiver. The viewer connects automatically, without browser serial permissions
or a port picker. Unplugged devices are rediscovered automatically. One viewer
tab can control the receiver at a time. No flashing is needed. When the firmware advertises 16 MS/s
on-chip spectra, connecting applies the QO-100 preset and view automatically;
**QO-100 · DATV preset** and **Reset QO-100 view** reapply them. Browser/device
selection remains under the operator's control. Stop the server with Ctrl-C.

Flask serves the files and bridges pyserial to the viewer over a local WebSocket.
Use **Quit C3SCOPE** in the header to stop Python and release the USB port.
Closing the last viewer tab also stops the app after a 10-second grace period;
refreshing the page or leaving another viewer tab open keeps it running.
Background tabs stay connected. Automatic shutdown is postponed during firmware
installation, and the Quit button is blocked until the installation finishes.
Ctrl-C remains available in the terminal. Ports without USB identification
are listed but not probed. Firmware flashing still uses the separate browser
installer; stop the Flask app first to release the serial port. No build step
or cloud account is required. Node.js is needed only for the automated checks:

```sh
node --test viewer/tests/*.test.mjs
```

## Scope and status

C3SCOPE includes experimental DATV spectrum hints below the waterfall. A
candidate must persist for at least one second across several spectra, have
measurable shoulders and a reasonably flat top, and span enough FFT bins.
The displayed frequency is the estimated signal center. Estimated SR uses
the noise-subtracted half-power width (approximately the symbol rate for an
ideal raised-cosine DVB power spectrum), rounded to a familiar rate when close.
See [ETSI TR 102 376, Figure 5 discussion](https://www.etsi.org/deliver/etsi_tr/102300_102399/102376/01.01.01_60/tr_102376v010101p.pdf).
This does not decode DVB, identify modulation/FEC, or confirm DATV. Other
signals can resemble DATV; weak, overlapping, distorted or edge-truncated
signals can be missed or estimated incorrectly. No hint does not mean a
frequency is clear. Detection currently targets roughly 50 kS/s–2.4 MS/s
within 2401–2410 MHz and needs AVG spectrum detection. Synthetic tests cover
125–2000 kS/s signals; real RF estimates still need comparison to known signals.

The intended display is 2401.000–2410.000 MHz local uplink RF. A future
downlink-equivalent label adds 8089.500 MHz; it does not measure satellite
reception or establish satellite channel availability. Amplitude is relative
dBFS, not calibrated dBm. C3 acquisition consists of snapshots with gaps.

The preset selects a firmware-advertised 16 MS/s on-chip spectrum profile
(2048 bins where offered) at 2406 MHz and crops all plots to 2401–2410 MHz
using the displayed frame's LO and sample rate. Without such a profile it
keeps upstream defaults and says why. Mathematical bin spacing at 2048 bins
is 7.8125 kHz, distinct from effective resolution bandwidth.

Done: baseline inspection, branding, QO-100 preset and crop, with automated
checks (186 passing, including exact crop boundaries and preset fallback).
**Not yet verified in a browser or with hardware**: the preset, crop and
branding need a real C3 connection, RF orientation and edge checks before
first-milestone acceptance. Downlink-equivalent axis, receiver frame-rate and
stale-data display, and saved preferences are outstanding. See
[baseline notes](BASELINE.md) for evidence and protocol details.

## Attribution and repository layout

`viewer/` is a full local Git clone of
[ESPARGOS/esp-web-sdr](https://github.com/ESPARGOS/esp-web-sdr), retaining its
history, README, GPL-3.0-or-later license and third-party notices. Upstream
contributors include Florian Euchner and Zoltan Doczi. This project is an
independent adaptation, without implied ESPARGOS endorsement.

The supplied brief and these project notes live outside that clone for now.
No remote fork has been created. Run Git commands from `viewer/` when
inspecting upstream history. Other projects have not been modified.
