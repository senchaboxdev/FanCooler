#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate ClaudeCooler icons (classic Aqua gel-orb style) into /tmp.

Coral Claude-branded gel orb (#d97757 "Crail") with the Claude starburst
mark in white — an irregular radial burst of tapered rays.

Outputs (consumed by build_app.sh — paths are a functional contract,
do NOT rename them):
    /tmp/icon_<size>.png        for size in 16 32 64 128 256 512 1024
    /tmp/fancooler_menubar.png  monochrome template glyph for the menu bar

Python 3.6 compatible. Pillow only.
"""
import math
from PIL import Image, ImageDraw, ImageFilter

# ---------------------------------------------------------------- palette
# Claude coral gel: brand color #d97757, gel range light -> dark rim
GEL_LIGHT = (0xf0, 0xa9, 0x8c)   # focus highlight inside the orb
GEL_MID   = (0xd9, 0x77, 0x57)   # body — Claude "Crail" coral
GEL_DARK  = (0xa8, 0x4e, 0x2e)   # rim
RIM_EDGE  = (0x82, 0x39, 0x1d)   # outermost ring


def _lerp(c1, c2, t):
    return tuple(int(round(c1[i] + (c2[i] - c1[i]) * t)) for i in range(3))


# ------------------------------------------------------------- starburst
# Irregular radial burst: tapered rays of slightly varying length and
# spacing — organic, not a perfect geometric star.
RAYS_LARGE = [   # 14 rays — full-detail mark for 64px and up
    (90, 1.00), (113, 0.84), (139, 0.95), (168, 0.78), (193, 0.90),
    (215, 0.99), (243, 0.81), (266, 0.92), (291, 0.85), (317, 0.98),
    (344, 0.79), (10, 0.94), (35, 0.83), (62, 0.97),
]
RAYS_SMALL = [   # 10 chunkier rays — keeps the mark legible at 16/32px
    (90, 1.00), (126, 0.78), (161, 0.95), (197, 0.76), (233, 0.97),
    (270, 0.82), (305, 0.92), (341, 0.77), (17, 0.96), (54, 0.79),
]


def _starburst_mask(size, cx, cy, radius, rays, w_frac):
    """Greyscale mask (white = glyph) of the Claude starburst.

    Each ray is a four-point spike: near-point at the center, widest at
    ~38% of its length, pointed tip — tapered at both ends."""
    m = Image.new('L', (size, size), 0)
    d = ImageDraw.Draw(m)
    for ang, frac in rays:
        a = math.radians(ang)
        ux, uy = math.cos(a), -math.sin(a)     # image y axis points down
        px, py = -uy, ux                       # perpendicular
        L = radius * frac
        w = radius * w_frac * (0.72 + 0.45 * frac)
        d.polygon([
            (cx - ux * radius * 0.04,          cy - uy * radius * 0.04),
            (cx + ux * L * 0.38 + px * w,      cy + uy * L * 0.38 + py * w),
            (cx + ux * L,                      cy + uy * L),
            (cx + ux * L * 0.38 - px * w,      cy + uy * L * 0.38 - py * w),
        ], fill=255)
    # small solid hub so the converging rays read as one mark
    hub = radius * 0.10
    d.ellipse([cx - hub, cy - hub, cx + hub, cy + hub], fill=255)
    return m


def _render_orb_master(canvas, detail='large'):
    """Render the full Aqua orb + starburst glyph at `canvas` px (RGBA)."""
    W = canvas
    img = Image.new('RGBA', (W, W), (0, 0, 0, 0))

    cx, cy = W * 0.5, W * 0.47          # orb sits slightly high...
    R = W * 0.42                        # ...leaving room for the shadow

    # ---- soft drop shadow under the orb -------------------------------
    sh = Image.new('RGBA', (W, W), (0, 0, 0, 0))
    sd = ImageDraw.Draw(sh)
    sw, shh = R * 1.55, R * 0.34
    sy = cy + R * 0.88
    sd.ellipse([cx - sw / 2, sy - shh / 2, cx + sw / 2, sy + shh / 2],
               fill=(45, 16, 6, 110))
    sh = sh.filter(ImageFilter.GaussianBlur(R * 0.055))
    img = Image.alpha_composite(img, sh)

    # ---- gel sphere: offset radial gradient ----------------------------
    orb = Image.new('RGBA', (W, W), (0, 0, 0, 0))
    od = ImageDraw.Draw(orb)
    fx, fy = cx, cy - R * 0.30          # gradient focus above center
    N = 360
    for i in range(N, 0, -1):
        f = i / float(N)                # 1 = rim, ->0 = focus
        ccx = fx + (cx - fx) * f
        ccy = fy + (cy - fy) * f
        rad = R * f
        if f > 0.55:
            col = _lerp(GEL_MID, GEL_DARK, (f - 0.55) / 0.45)
        else:
            col = _lerp(GEL_LIGHT, GEL_MID, f / 0.55)
        od.ellipse([ccx - rad, ccy - rad, ccx + rad, ccy + rad],
                   fill=col + (255,))

    # circular clip mask for everything painted on the orb
    clip = Image.new('L', (W, W), 0)
    ImageDraw.Draw(clip).ellipse([cx - R, cy - R, cx + R, cy + R], fill=255)

    # ---- bottom refraction glow (classic gel bounce light) ------------
    glow = Image.new('RGBA', (W, W), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gw, gh = R * 1.5, R * 0.85
    gy = cy + R * 0.62
    gd.ellipse([cx - gw / 2, gy - gh / 2, cx + gw / 2, gy + gh / 2],
               fill=(255, 206, 178, 120))
    glow = glow.filter(ImageFilter.GaussianBlur(R * 0.10))
    glow.putalpha(Image.composite(glow.split()[3],
                                  Image.new('L', (W, W), 0), clip))
    orb = Image.alpha_composite(orb, glow)

    # ---- Claude starburst glyph (white) --------------------------------
    if detail == 'small':
        rays, w_frac, g_radius, g_alpha = RAYS_SMALL, 0.135, R * 0.80, 1.0
    else:
        rays, w_frac, g_radius, g_alpha = RAYS_LARGE, 0.090, R * 0.78, 0.96
    gm = _starburst_mask(W, cx, cy, g_radius, rays, w_frac)
    # faint dark backdrop behind glyph for depth
    shadow_glyph = gm.filter(ImageFilter.GaussianBlur(W * 0.008))
    dark = Image.new('RGBA', (W, W), (110, 38, 14, 0))
    dark.putalpha(shadow_glyph.point(lambda a: int(a * 0.45)))
    orb = Image.alpha_composite(orb, dark)
    white = Image.new('RGBA', (W, W), (255, 255, 255, 0))
    white.putalpha(gm.point(lambda a: int(a * g_alpha)))
    orb = Image.alpha_composite(orb, white)

    # ---- rim: darker outer ring for definition -------------------------
    rim = Image.new('RGBA', (W, W), (0, 0, 0, 0))
    rd = ImageDraw.Draw(rim)
    rw = max(2, int(R * (0.035 if detail == 'small' else 0.022)))
    rd.ellipse([cx - R + rw / 2, cy - R + rw / 2,
                cx + R - rw / 2, cy + R - rw / 2],
               outline=RIM_EDGE + (235,), width=rw)
    rim = rim.filter(ImageFilter.GaussianBlur(rw * 0.4))
    orb = Image.alpha_composite(orb, rim)

    # ---- top specular gloss crescent (the Aqua signature) --------------
    gloss = Image.new('RGBA', (W, W), (0, 0, 0, 0))
    gx0, gx1 = cx - R * 0.74, cx + R * 0.74
    gy0, gy1 = cy - R * 0.94, cy - R * 0.10
    gmask = Image.new('L', (W, W), 0)
    ImageDraw.Draw(gmask).ellipse([gx0, gy0, gx1, gy1], fill=255)
    # vertical fade: bright at top edge -> transparent at crescent bottom
    grad = Image.new('L', (W, W), 0)
    gdr = ImageDraw.Draw(grad)
    top, bot = int(gy0), int(gy1)
    for y in range(top, bot + 1):
        t = (y - top) / float(max(1, bot - top))
        gdr.line([(0, y), (W, y)], fill=int(205 * (1.0 - t) ** 1.5))
    gmask = Image.composite(grad, Image.new('L', (W, W), 0), gmask)
    gloss = Image.new('RGBA', (W, W), (255, 255, 255, 0))
    gloss.putalpha(gmask)
    orb = Image.alpha_composite(orb, gloss)

    # clip orb stack to the circle, composite over shadow
    orb.putalpha(Image.composite(orb.split()[3],
                                 Image.new('L', (W, W), 0), clip))
    return Image.alpha_composite(img, orb)


def _make_menubar_glyph(path, point_size=44, supersample=8):
    """Monochrome (black on transparent) template starburst for the
    status bar — rendered supersampled, then LANCZOS-downsampled."""
    S = point_size * supersample
    cx = cy = S / 2.0
    R = S * 0.47
    gm = _starburst_mask(S, cx, cy, R, RAYS_SMALL, w_frac=0.13)
    out = Image.new('RGBA', (S, S), (0, 0, 0, 0))
    black = Image.new('RGBA', (S, S), (0, 0, 0, 255))
    out = Image.composite(black, out, gm)
    out = out.resize((point_size, point_size), Image.LANCZOS)
    out.save(path)


def main():
    large = _render_orb_master(2048, detail='large')
    small = _render_orb_master(1024, detail='small')
    for sz in [16, 32, 64, 128, 256, 512, 1024]:
        src = small if sz <= 32 else large
        src.resize((sz, sz), Image.LANCZOS).save(
            '/tmp/icon_{}.png'.format(sz))
    _make_menubar_glyph('/tmp/fancooler_menubar.png')


if __name__ == '__main__':
    main()
