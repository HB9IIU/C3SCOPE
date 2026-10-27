# Third-party software and attribution

C3SCOPE is an independent HB9IIU adaptation, without ESPARGOS endorsement.

Original C3SCOPE code is GPL-3.0-or-later; see COPYING.md and LICENSE.
Third-party components retain their respective licences below.

| Component | Source / notices | License |
| --- | --- | --- |
| ESP-WebSDR viewer | <https://github.com/ESPARGOS/esp-web-sdr>; `viewer/LICENSE`, `BASELINE.md` | GPL-3.0-or-later |
| ESP-SDR receiver firmware | `third_party/firmware/README.md`, source archives and `LICENSE-ESP-SDR` | GPL-3.0-or-later |
| ESP-DSP and ESP-IDF components | Notices in the firmware source archives and SDK sources referenced there | Component-specific; retain their notices |
| esptool-js, pako, tslib, atob-lite | `viewer/flasher/vendor/LICENSE-*` and provenance JSON | See the respective included licenses |
| Carlito font | `viewer/fonts.css` contains the font license | SIL Open Font License 1.1 |
| Embedded Python | Official python.org Windows runtime; `python/LICENSE.txt` in the portable package | PSF and bundled-library notices |
| Flask, pyserial, esptool and Python dependencies | Exact release versions in `requirements-lock.txt`; source and license files in the portable package's `python/Lib/site-packages/` | Each package's included license |

The portable package includes application Python sources under `app/`, viewer
sources under `app/viewer/`, and the receiver firmware source archives under
`third_party/firmware/`. Firmware build references and limitations are recorded
there. Source for the complete C3SCOPE project, including packaging scripts:
<https://github.com/HB9IIU/C3SCOPE>.

Upstream contributors include Florian Euchner and Zoltan Doczi; on-chip spectrum
contributions are credited to <https://www.z2labs.io>. See the upstream projects
for their full contributor histories. This repository preserves an adapted
snapshot, not a copy of the upstream Git history.
