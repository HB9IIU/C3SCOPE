# Bundled receiver firmware source and notices

The binary files in `viewer/firmware/` are the unmodified ESPARGOS ESP-SDR
artifacts identified by that directory's `manifest.json` and each profile's
`build-info.json`. All bundled profiles identify firmware revision
`b1e65189a900542ff18358095e01506b3e513afc`.

ESP-SDR is GPL-3.0-or-later; its license is included as `LICENSE-ESP-SDR`.
Upstream authors retain their copyright. ESP-DSP and SDK components retain
their own licenses and notices.

## Source archives

`sources.json` records the repository, exact revision, original download URL,
and SHA-256 of each source archive stored alongside this file:

- ESP-SDR: firmware source, profile catalog, configuration, export scripts,
  dependency lock file, CI build instructions, and licensing notices.
- ESP-DSP: source of the pinned `components/esp-dsp` submodule, including its
  own license. Place the extracted contents at `components/esp-dsp` inside
  the extracted ESP-SDR source before building.

GitHub's source archive does not populate Git submodules automatically; the
second archive is supplied for that reason. Use the recorded commits, not
the current default branches.

## Rebuilding

Follow the included ESP-SDR `README.md`, `.github/workflows/firmware.yml`, and
`tools/build_firmware.py`. `firmware-targets.json` selects the pinned ESP-IDF
revision for each profile. The XIAO ESP32-C3 profile uses ESP-IDF revision
`25fe69f946311abdaf9ad56591f25fedbc20ac98` from
<https://github.com/espressif/esp-idf> (with its SDK submodules).

The upstream build workflow installs that SDK and its toolchain, then runs:

```sh
python tools/build_firmware.py --profile esp32c3 --version b1e65189a900542ff18358095e01506b3e513afc --output artifacts
```

The ESP-IDF SDK/toolchain and managed components are fetched by the upstream
build instructions; they are not included in these two archives. Their exact
references are preserved in the profile catalog, build metadata, and upstream
dependency configuration. No local firmware modifications are claimed.

SHA-256 and MD5 checksums in `viewer/firmware/manifest.json` validate the
distributed binary files. A rebuild can have different hashes because build
timestamps and build environment data are embedded. This review did not run
a complete ESP-IDF firmware rebuild.
