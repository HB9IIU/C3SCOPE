C3SCOPE - See your signal.
A 5 EUR QO-100 DATV uplink spectrum viewer (2401-2410 MHz) by HB9IIU.

QUICK START
1. Plug in a second XIAO ESP32-C3 with receiver firmware, using a USB DATA cable.
   Close any serial monitor that has its port open.
2. Double-click C3SCOPE.bat. A console window opens and shows the address.
   Windows may ask for confirmation because the files are not code-signed.
3. Your browser opens at http://127.0.0.1:8000 (next free port up to 8019 if busy).
4. The receiver is detected and connected automatically.
   If the board is blank, use the guided setup in the page to flash it.

Stop with "Quit C3SCOPE" in the page, or Ctrl-C in the console window.
Python is bundled; nothing needs installing.

NOTES
- Levels are relative dBFS, not calibrated dBm.
- C3SCOPE only listens. Never connect a transmitter output directly to the C3.
- DATV hints are experimental and do not confirm DATV.

Based on ESPARGOS ESP-SDR / ESP-WebSDR (GPL-3.0-or-later).
Original C3SCOPE code: GPL-3.0-or-later. See COPYING.md and LICENSE.
Licenses and attribution: THIRD_PARTY.md and app/viewer/LICENSE.
Application sources: C3SCOPE-source.zip, published next to this download on the Releases page.
Receiver firmware sources and build references: third_party/firmware/.
Full documentation: https://github.com/HB9IIU/C3SCOPE
