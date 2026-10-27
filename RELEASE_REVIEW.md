# Pre-publication review — 27 October 2026

Scope: tracked source, Git history secret scan, viewer, backend, USB discovery,
firmware workflow, LAN controls, documentation, third-party assets, dependencies
and Windows portable packaging. This is an engineering review, not a legal opinion
or a guarantee that every defect has been found.

## Fixed

- Restricted remote serial writes and signal controls so LAN viewers cannot use
  the raw bridge for bootloader flashing or GPIO actuation.
- Added Host validation to reduce DNS-rebinding exposure of local admin actions,
  request/message size limits, and graceful rejection of malformed setup JSON.
- Discarded stale probe results when a different USB identity reuses a COM port.
- Made portable builds preserve unrelated dist files, verify the embedded Python
  download, pin dependency versions and package wheels for the shipped interpreter.
- Updated the bundled runtime to Python 3.13.17 and added release checksums,
  build metadata, complete application source packaging and firmware source archives.
- Corrected the claim that upstream Git history was retained; documented
  modifications, third-party provenance and the trusted-network LAN model.
- Added ignore rules for common local environment and private-key files.

## Verification

- 47 Python tests and 209 viewer tests pass.
- pip check passes; pip-audit found no known vulnerabilities in the 27 resolved
  Python dependencies at review time.
- All 33 firmware images match manifest size, SHA256 and MD5 values.
- Common credential/private-key patterns were absent from tracked text and Git
  history text blobs. This does not detect every possible form of sensitive data.
- Portable and source ZIP integrity checks pass, app source matches the working
  tree, and no Git metadata, bytecode caches or environment files are included.
- The embedded interpreter imports the app and native dependencies and validates
  firmware assets. A mocked-receiver HTTP startup/quit smoke test passed.
- Main HTML structure and local runtime asset references were checked.

## Before publishing

1. Licence decision completed: original C3SCOPE code is GPL-3.0-or-later,
   documented in COPYING.md and LICENSE. Upstream licences remain in force.
2. Publish C3SCOPE-source.zip alongside C3SCOPE-portable.zip and its checksum.
   Retain THIRD_PARTY.md, MODIFICATIONS.md and bundled notices/source archives.
3. Run a final real-board acceptance check: cold start, hot plug, unplug/replug,
   C3CAST warning, and intentional factory-board flash/reinstall/erase confirmation.
   This review did not flash or erase connected hardware.
4. Confirm firmware source/build references satisfy your distribution needs.
   A complete ESP-IDF firmware rebuild and exhaustive legal review were not performed.

LAN mode intentionally has no login or TLS and is for a trusted private network.
Changes are local and the running app needs a restart to use the reviewed code.
