"""Build the static browser flasher published on GitHub Pages (docs/).

The page reuses the viewer's own installer code and the bundled XIAO ESP32-C3
firmware, so it cannot drift from what the Windows app installs.
Run from the project root:  python tools/build_web_flasher.py
"""
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VIEWER = ROOT / 'viewer'
SITE = ROOT / 'docs'
PROFILE = 'esp32c3'

ASSETS = ['serial-transport.js', 'fonts.css', 'c3scope.svg',
          'favicon-16x16.png', 'favicon-32x32.png', 'favicon-194x194.png']
FLASHER_FILES = ['app.js', 'catalog.mjs', 'reset.mjs', 'style.css']


def main():
    for path in (SITE / 'flasher', SITE / 'firmware'):
        if path.exists():
            shutil.rmtree(path)
    shutil.copy(ROOT / 'tools' / 'web_flasher.html', SITE / 'index.html')
    shutil.copy(ROOT / 'tools' / 'web_flasher.css', SITE / 'site.css')
    for name in ASSETS:
        shutil.copy(VIEWER / name, SITE / name)
    (SITE / 'flasher').mkdir(parents=True)
    for name in FLASHER_FILES:
        shutil.copy(VIEWER / 'flasher' / name, SITE / 'flasher' / name)
    shutil.copytree(VIEWER / 'flasher' / 'vendor', SITE / 'flasher' / 'vendor')
    # The installer's own message names its button; this page labels it differently.
    app = SITE / 'flasher' / 'app.js'
    text = app.read_text(encoding='utf-8')
    old = 'then select Install ESP-SDR firmware.'
    assert old in text, 'installer message changed upstream; update tools/build_web_flasher.py'
    app.write_text(text.replace(old, 'then press the Install button.'), encoding='utf-8')

    manifest = json.loads((VIEWER / 'firmware' / 'manifest.json').read_text(encoding='utf-8'))
    manifest['variants'] = {PROFILE: manifest['variants'][PROFILE]}
    (SITE / 'firmware').mkdir()
    (SITE / 'firmware' / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    shutil.copytree(VIEWER / 'firmware' / PROFILE, SITE / 'firmware' / PROFILE)
    (SITE / '.nojekyll').write_text('', encoding='utf-8')
    print(f'Web flasher written to {SITE}')


if __name__ == '__main__':
    main()
