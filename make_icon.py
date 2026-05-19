#!/usr/bin/env python3
"""Generate FanCooler icon PNGs at multiple sizes into /tmp/icon_<size>.png"""
import struct, zlib, math

def png_chunk(name, data):
    c = zlib.crc32(name + data) & 0xffffffff
    return struct.pack('>I', len(data)) + name + data + struct.pack('>I', c)

def make_png(size):
    w = h = size
    cx = cy = w / 2.0
    r = w / 2.0 - 2
    rows = []
    for y in range(h):
        row = []
        for x in range(w):
            dx = x - cx; dy = y - cy
            dist = math.sqrt(dx*dx + dy*dy)
            angle = math.degrees(math.atan2(dy, dx)) % 360
            if dist > r:
                row += [0, 0, 0, 0]; continue
            drawn = False
            for k in range(3):
                a = (angle - k * 120) % 360
                inner = 0.18 * r
                outer = 0.82 * r
                if inner < dist < outer and 10 < a < 80:
                    fade = min(a - 10, 80 - a,
                               (dist - inner) / max(r * 0.08, 1),
                               (outer - dist) / max(r * 0.08, 1))
                    if fade > 0:
                        t = min(1.0, fade / 6.0)
                        row += [int(88 + 80*t), int(166 + 50*t), 255, int(200 + 55*t)]
                        drawn = True; break
            if not drawn:
                if dist < r * 0.14:
                    row += [88, 166, 255, 255]
                else:
                    row += [22, 27, 34, 255]
        rows.append(row)

    raw = b''
    for row in rows:
        raw += b'\x00' + bytes(row)
    compressed = zlib.compress(raw, 9)
    sig = b'\x89PNG\r\n\x1a\n'
    ihdr = png_chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 6, 0, 0, 0))
    idat = png_chunk(b'IDAT', compressed)
    iend = png_chunk(b'IEND', b'')
    return sig + ihdr + idat + iend

for sz in [16, 32, 64, 128, 256, 512, 1024]:
    with open('/tmp/icon_{}.png'.format(sz), 'wb') as f:
        f.write(make_png(sz))
