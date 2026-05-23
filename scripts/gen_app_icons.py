"""Generate app icons for the Valueland mobile app.

Produces the four assets referenced by mobile/app.json:
    assets/icon.png            (1024x1024)  iOS + Android base
    assets/adaptive-icon.png   (1024x1024)  Android foreground (transparent bg)
    assets/splash.png          (1284x2778)  Launch screen
    assets/favicon.png         (96x96)      Web

The design: a bold white "V" letterform on the brand-green square
(#166534) with a subtle upward chart line accent below it.
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

BRAND_GREEN = (22, 101, 52)
WHITE = (255, 255, 255)
LIGHT_GREEN = (74, 222, 128)

ASSETS = Path(__file__).parent.parent / "mobile" / "assets"
ASSETS.mkdir(parents=True, exist_ok=True)


def _find_bold_font(size: int) -> ImageFont.FreeTypeFont:
    """Walk the usual Linux font locations and grab a bold sans."""
    candidates = [
        "/usr/local/share/fonts/dejavu-sans-fonts/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
        "/usr/local/share/fonts/liberation-sans-fonts/LiberationSans-Bold.ttf",
        "/usr/share/fonts/liberation-sans-fonts/LiberationSans-Bold.ttf",
        "/usr/share/fonts/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/local/share/fonts/lato-fonts/Lato-Bold.ttf",
    ]
    for p in candidates:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    raise RuntimeError(
        "No bold sans TTF found. Install dejavu-sans-fonts or liberation-sans-fonts."
    )


def _draw_logo(canvas: Image.Image, *, with_bg: bool) -> None:
    """Paint the 'V' + chart-line accent onto an already-sized canvas."""
    w, h = canvas.size
    draw = ImageDraw.Draw(canvas)
    if with_bg:
        draw.rectangle([(0, 0), (w, h)], fill=BRAND_GREEN)

    # The V — sized to ~60% of the shorter dimension
    short = min(w, h)
    font_px = int(short * 0.62)
    font = _find_bold_font(font_px)

    text = "V"
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    tx = (w - tw) // 2 - bbox[0]
    ty = (h - th) // 2 - bbox[1] - int(short * 0.04)
    draw.text((tx, ty), text, font=font, fill=WHITE)

    # Upward chart line beneath the V — three rising segments
    line_y = h // 2 + int(short * 0.28)
    span = int(short * 0.42)
    x0 = (w - span) // 2
    points = [
        (x0,                       line_y),
        (x0 + span // 3,           line_y - int(short * 0.04)),
        (x0 + (2 * span) // 3,     line_y - int(short * 0.02)),
        (x0 + span,                line_y - int(short * 0.10)),
    ]
    width = max(4, int(short * 0.012))
    draw.line(points, fill=LIGHT_GREEN, width=width, joint="curve")
    # End dot
    r = max(5, int(short * 0.018))
    ex, ey = points[-1]
    draw.ellipse([(ex - r, ey - r), (ex + r, ey + r)], fill=LIGHT_GREEN)


def main() -> None:
    # ---- icon.png (1024x1024, solid green bg, no alpha for iOS) ----
    icon = Image.new("RGB", (1024, 1024), BRAND_GREEN)
    _draw_logo(icon, with_bg=False)
    icon.save(ASSETS / "icon.png", "PNG")
    print(f"wrote {ASSETS / 'icon.png'}")

    # ---- adaptive-icon.png (Android foreground, transparent bg) ----
    adaptive = Image.new("RGBA", (1024, 1024), (0, 0, 0, 0))
    _draw_logo(adaptive, with_bg=True)
    adaptive.save(ASSETS / "adaptive-icon.png", "PNG")
    print(f"wrote {ASSETS / 'adaptive-icon.png'}")

    # ---- splash.png (1284x2778 — fits modern iPhone, RGB, green bg) ----
    splash = Image.new("RGB", (1284, 2778), BRAND_GREEN)
    # Logo in the centre, sized to ~50% of width
    logo_size = 640
    logo = Image.new("RGB", (logo_size, logo_size), BRAND_GREEN)
    _draw_logo(logo, with_bg=False)
    splash.paste(
        logo,
        ((splash.width - logo_size) // 2, (splash.height - logo_size) // 2),
    )
    splash.save(ASSETS / "splash.png", "PNG")
    print(f"wrote {ASSETS / 'splash.png'}")

    # ---- favicon.png (web) ----
    fav = Image.new("RGB", (96, 96), BRAND_GREEN)
    _draw_logo(fav, with_bg=False)
    fav.save(ASSETS / "favicon.png", "PNG")
    print(f"wrote {ASSETS / 'favicon.png'}")


if __name__ == "__main__":
    main()
