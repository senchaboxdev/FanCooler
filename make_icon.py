#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate FanCooler icons (classic Aqua gel-orb style) into /tmp.

Outputs (consumed by build_app.sh):
    /tmp/icon_<size>.png        for size in 16 32 64 128 256 512 1024
    /tmp/fancooler_menubar.png  monochrome template glyph for the menu bar

Python 3.6 compatible. Pillow only.
"""
import math
from PIL import Image, ImageDraw, ImageFilter

# ---------------------------------------------------------------- palette
# Matches the dashboard Aqua theme: primary #2f6fce, gel #6eb2f2 -> #2b66c4
GEL_LIGHT = (0x86, 0xc2, 0xf7)   # focus highlight inside the orb
GEL_MID   = (0x3f, 0x86, 0xe0)   # body
GEL_DARK  = (0x1b, 0x4e, 0xa8)   # rim
RIM_EDGE  = (0x12, 0x3c, 0x86)   # outermost ring


def _lerp(c1, c2, t):
    return tuple(int(round(c1[i] + (c2[i] - c1[i]) * t)) for i in range(3))


def _blade_polygon(cx, cy, r_inner, r_outer, base_deg, sweep_deg,
                   w_peak_deg, steps=64):
    """Swept fan-blade outline: leading edge out, trailing edge back."""
    lead, trail = [], []
    for i in range(steps + 1):
        t = i / float(steps)
        ang = base_deg + sweep_deg * t
        rad = r_inner + (r_outer - r_inner) * t
        # tapered at hub and tip, widest ~60% out
        w = w_peak_deg * (0.30 + 0.70 * math.sin(math.pi * t) ** 0.85)
        la, ta = math.radians(ang + w), math.radians(ang - w)
        lead.append((cx + rad * math.cos(la), cy + rad * math.sin(la)))
        trail.append((cx + rad * math.cos(ta), cy + rad * math.sin(ta)))
    return lead + trail[::-1]


def _fan_glyph_mask(size, cx, cy, radius, blade_w_deg, hub_frac,
                    hole_frac, sweep_deg=58.0, blades=3):
    """Greyscale mask (white = glyph) of swept blades + hub."""
    m = Image.new('L', (size, size), 0)
    d = ImageDraw.Draw(m)
    for k in range(blades):
        base = -90.0 + k * (360.0 / blades)
        poly = _blade_polygon(cx, cy, radius * 0.16, radius,
                              base, sweep_deg, blade_w_deg)
        d.polygon(poly, fill=255)
    hub = radius * hub_frac
    d.ellipse([cx - hub, cy - hub, cx + hub, cy + hub], fill=255)
    if hole_frac > 0:
        hole = radius * hole_frac
        d.ellipse([cx - hole, cy - hole, cx + hole, cy + hole], fill=0)
    return m


def _render_orb_master(canvas, detail='large'):
    """Render the full Aqua orb + fan glyph at `canvas` px (RGBA)."""
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
               fill=(10, 20, 45, 110))
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
               fill=(160, 215, 255, 120))
    glow = glow.filter(ImageFilter.GaussianBlur(R * 0.10))
    glow.putalpha(Image.composite(glow.split()[3],
                                  Image.new('L', (W, W), 0), clip))
    orb = Image.alpha_composite(orb, glow)

    # ---- fan glyph (white, slightly translucent) -----------------------
    if detail == 'small':
        blade_w, hub_f, hole_f, sweep, g_alpha = 34.0, 0.34, 0.0, 40.0, 1.0
    else:
        blade_w, hub_f, hole_f, sweep, g_alpha = 23.0, 0.24, 0.085, 58.0, 0.93
    gm = _fan_glyph_mask(W, cx, cy, R * 0.74, blade_w, hub_f, hole_f, sweep)
    # faint dark backdrop behind glyph for depth
    shadow_glyph = gm.filter(ImageFilter.GaussianBlur(W * 0.008))
    dark = Image.new('RGBA', (W, W), (12, 38, 92, 0))
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
    """Monochrome (black on transparent) template fan for the status bar."""
    S = point_size * supersample
    cx = cy = S / 2.0
    R = S * 0.46
    gm = _fan_glyph_mask(S, cx, cy, R, blade_w_deg=30.0, hub_frac=0.30,
                         hole_frac=0.115, sweep_deg=48.0)
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
