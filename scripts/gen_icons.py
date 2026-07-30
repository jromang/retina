"""Derive every application icon from the source logo.

    python scripts/gen_icons.py

A **deliberate** act, like `gen_web_fixtures.py`: the artefacts are versioned, and we only
regenerate them when the logo changes. Regenerating on every build would move binaries around
in the history for no reason.

Source: `python/retina/resources/branding/logo-avex.png`. It lives **inside the package** and
not at the root of the repository, for three cumulative reasons:

- `[tool.maturin] include` already covers `resources/**/*` → the icon ships in the wheel;
- `sources = ["python/retina"]` carries it along into the briefcase bundle → it is present at
  runtime in the installed application;
- the native shell needs a **path** at launch (`--icon`), not a compiled resource.

Outputs:

    python/retina/resources/branding/retina.ico          Windows: window, MSI, shortcut
    python/retina/resources/branding/retina-<N>.png      Linux (briefcase expects this pattern)
    web/public/favicon.png                               browser tab + title-bar logo
                                                         (`<img src="/favicon.png">`)

The logo is **cropped to its alpha** before scaling: the source PNG has wide transparent
margins, without which the chevron would only fill a third of a 16 px icon.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRANDING = ROOT / "python" / "retina" / "resources" / "branding"
SOURCE = BRANDING / "logo-avex.png"
FAVICON = ROOT / "web" / "public" / "favicon.png"

#: Sizes embedded in the .ico. 256 is needed by Explorer's "large icons" view, 16 by the one
#: in the title bar.
ICO_SIZES = [16, 24, 32, 48, 64, 128, 256]
#: PNG sizes briefcase expects on Linux (`<base>-<size>.png`).
PNG_SIZES = [16, 32, 64, 128, 256, 512]
#: Margin around the logo, as a fraction of the side. An icon flush against the edges looks too
#: big next to the system icons, which all breathe a little.
MARGIN = 0.06


def _square(source: Path):
    """Load the logo, crop it to its content and center it in a transparent square."""
    from PIL import Image

    image = Image.open(source).convert("RGBA")
    bbox = image.getchannel("A").getbbox()
    if bbox is not None:
        image = image.crop(bbox)

    side = int(max(image.size) / (1 - 2 * MARGIN))
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(image, ((side - image.width) // 2, (side - image.height) // 2))
    return canvas


def main() -> int:
    try:
        from PIL import Image  # noqa: F401  — imported for the error message alone
    except ImportError:
        print("[icons] Pillow required:  pip install pillow", file=sys.stderr)
        return 1

    if not SOURCE.is_file():
        print(f"[icons] source logo not found: {SOURCE}", file=sys.stderr)
        return 1

    logo = _square(SOURCE)
    print(f"[icons] source {SOURCE.name} -> square {logo.width}x{logo.height}", flush=True)

    ico = BRANDING / "retina.ico"
    logo.save(ico, format="ICO", sizes=[(s, s) for s in ICO_SIZES])
    print(f"[icons] {ico.relative_to(ROOT)} ({ico.stat().st_size / 1024:.0f} KB, {ICO_SIZES})")

    from PIL import Image as PILImage

    for size in PNG_SIZES:
        target = BRANDING / f"retina-{size}.png"
        logo.resize((size, size), PILImage.LANCZOS).save(target, format="PNG")
    print(f"[icons] {len(PNG_SIZES)} PNG retina-<size>.png")

    FAVICON.parent.mkdir(parents=True, exist_ok=True)
    logo.resize((128, 128), PILImage.LANCZOS).save(FAVICON, format="PNG")
    print(f"[icons] {FAVICON.relative_to(ROOT)} (128x128)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
