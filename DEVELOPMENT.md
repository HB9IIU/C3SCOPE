# C3SCOPE development

## Run from source

```sh
python -m pip install -r requirements.txt
python app.py
```

Options: `--port N` (first port to try), `--no-browser`, `--lan`.

## Build the portable zip

```powershell
powershell -File build_portable.ps1
```

This downloads the checksum-pinned official Windows Python runtime from
`packaging/windows-runtime.json`, installs the exact dependencies in
`requirements-lock.txt`, and writes `dist\C3SCOPE-portable.zip` plus a SHA-256
file. Only `dist\C3SCOPE` and `build\portable-source` are replaced; unrelated
files in `dist` are preserved. The build verifies the shipped interpreter,
native wheels and receiver firmware before creating the zip.

The package includes the application source snapshot, firmware/DSP source
archives, third-party notices, and `BUILD-INFO.json`. See `THIRD_PARTY.md` and
`third_party/firmware/README.md`. It uses an embeddable Python and `.bat` launcher
rather than a PyInstaller executable. The plain-text readme comes from
`portable-readme.txt`.

To publish: `gh release upload <tag> dist/C3SCOPE-portable.zip --clobber`.

## Tests

```sh
node --test viewer/tests/*.test.mjs
python -m unittest
```

Node.js is used only for these tests.

## Firmware tools in the page

- Receiver firmware updates use the same guided installer. **Setup → Reinstall
  receiver firmware…** is also available for recovery, even without an update.
  Reviewing or cancelling leaves reception running; confirming pauses reception,
  erases the selected board, installs and verifies the bundled firmware, and
  reconnects automatically. Settings and files on the PC are not erased.
- **Setup → Erase ESP32…** completely erases the selected XIAO after explicit
  confirmation and leaves it blank. It does not install replacement firmware;
  use guided setup afterward to make it a C3SCOPE receiver again.

## Access from another PC on your LAN

Start the host PC with the ESP connected:

```sh
python app.py --lan --no-browser
```

Open the **LAN viewer** URL printed in the terminal on the other PC, for example
`http://192.168.1.50:8000`. The selected port may differ if 8000 is occupied.
Only one tab controls the receiver at a time: close an existing viewer before
opening it elsewhere. `--lan` keeps the host running after tabs close. Stop it
with Ctrl-C, or use **Quit C3SCOPE** at the host's `http://127.0.0.1:PORT` address.
Firmware installation, erasing and quitting are blocked for remote PCs.
Use this mode on your trusted LAN. If Windows asks, allow access on your private
network; the host firewall must allow the chosen port. No router port forwarding
is needed. Without `--lan`, the existing local-only automatic shutdown remains.
LAN access uses plain HTTP without authentication; any trusted LAN client can
claim the available receiver session. Its serial bridge accepts receiver
commands only. Bootloader packets, GPIO actuation and bootloader control signals
are not available over LAN. See [SECURITY.md](SECURITY.md).
C3SCOPE runs as a single instance: starting it again reuses the existing app
instead of launching another scanner. To switch a running local app into LAN
mode, quit it first, then start it with `--lan`.

## How it works

```
XIAO ESP32-C3 (ESP-SDR)  <--USB-->  Python / Flask (pyserial)  <--WebSocket-->  browser
```

The firmware captures the 2.4 GHz band and sends processed FFT spectra. The Python app owns the serial port, probes for a confirmed ESP-SDR receiver, and passes the data to the page over a local WebSocket. One viewer tab controls the receiver at a time.

See also [BASELINE.md](BASELINE.md) for provenance and protocol notes, and [DEVELOPMENT_NOTES.md](DEVELOPMENT_NOTES.md) for earlier developer notes.
