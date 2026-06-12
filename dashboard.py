#!/usr/bin/env python3
import tkinter as tk
import tkinter.font as tkfont
from tkinter import messagebox
import psutil
import subprocess
import platform
import math
import sys
import os
import fcntl

# ── Single-instance lock ──────────────────────────────────────────────────────
_LOCK_PATH = '/tmp/fancooler.lock'
_lock_fh   = None

def _try_acquire_lock():
    """Return True if we are the first instance, False if already running."""
    global _lock_fh
    try:
        _lock_fh = open(_LOCK_PATH, 'w')
        fcntl.flock(_lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        _lock_fh.write(str(os.getpid()))
        _lock_fh.flush()
        return True
    except IOError:
        return False

def _bring_to_front():
    """Raise the existing window via AppleScript."""
    for script in [
        'tell application "FanCooler" to activate',
        'tell application "System Events" to set frontmost of '
        '(first process whose bundle identifier is "com.senchabox.fancooler") to true',
    ]:
        try:
            subprocess.run(['osascript', '-e', script],
                           timeout=2,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            return
        except Exception:
            pass

if not _try_acquire_lock():
    _bring_to_front()
    sys.exit(0)
# ─────────────────────────────────────────────────────────────────────────────

try:
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    import matplotlib
    HAS_MPL = True
except ImportError:
    HAS_MPL = False

from monitor import SystemMonitor, load_config, save_config

# ── Classic Aqua palette (OS X 10.2–10.4) ─────────────────────────────────────
BG        = '#ececec'   # pinstripe base
STRIPE    = '#e2e2e2'   # pinstripe darker line
CARD      = '#ffffff'   # white panel body
BORDER    = '#b4b4b4'   # 1px panel border
SHADOW    = '#d2d2d2'   # soft drop line under panels
TEXT      = '#2a2a2a'
DIM       = '#707070'
ACCENT    = '#2f6fce'   # aqua blue
GREEN     = '#2e9e47'
YELLOW    = '#c9941a'
ORANGE    = '#e87722'
RED       = '#d23c3c'
BLUE      = '#3d80df'
TEAL      = '#0e8c8c'
GRAPHITE  = '#8e9aab'

# ── Typography — classic OS X system fonts ────────────────────────────────────
#   Lucida Grande — the Aqua-era system font: headers, body, buttons, tabs
#   Monaco        — classic mono: live numeric readouts (temp, RPM)
FONTS = {
    'display': ('Monaco', 24, 'bold'),          # gauge fallback
    'readout': ('Monaco', 17, 'bold'),          # stat-card value
    'header':  ('Lucida Grande', 13, 'bold'),   # section titles
    'brand':   ('Lucida Grande', 16, 'bold'),   # etched window title
    'body':    ('Lucida Grande', 12),           # descriptions, form labels
    'value':   ('Monaco', 11),                  # small live values
    'big_value': ('Monaco', 15, 'bold'),        # slider readouts
    'button':  ('Lucida Grande', 12),           # gel buttons
    'tab':     ('Lucida Grande', 11, 'bold'),   # segmented tab bar
    'label':   ('Lucida Grande', 10),           # status lines, footer
    'caption': ('Lucida Grande', 10),           # card titles, gauge units
    'micro':   ('Lucida Grande', 9),            # tiny captions
}

def temp_color(t):
    if t < 55:  return GREEN
    if t < 70:  return YELLOW
    if t < 80:  return ORANGE
    return RED

def fan_color(pct):
    if pct < 40: return GREEN
    if pct < 70: return YELLOW
    return RED


# ── Color helpers ─────────────────────────────────────────────────────────────
def _hex2rgb(c):
    return int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16)


def _mix(c1, c2, t):
    """Blend c1 toward c2 by t (0..1)."""
    r1, g1, b1 = _hex2rgb(c1)
    r2, g2, b2 = _hex2rgb(c2)
    return '#{:02x}{:02x}{:02x}'.format(
        int(r1 + (r2 - r1) * t),
        int(g1 + (g2 - g1) * t),
        int(b1 + (b2 - b1) * t))


def _tint(c, t):
    """Lighten toward white by t (0..1)."""
    return _mix(c, '#ffffff', t)


def _shade(hex_color, factor):
    """Darken a #rrggbb color by factor (0..1)."""
    r, g, b = _hex2rgb(hex_color)
    return '#{:02x}{:02x}{:02x}'.format(
        int(r * factor), int(g * factor), int(b * factor))


def _round_rect_pts(x0, y0, x1, y1, r, corners=(1, 1, 1, 1)):
    """Point list for a smooth=1 Canvas polygon: a rounded rectangle.
    corners = (tl, tr, br, bl); falsy entries stay square."""
    r = max(1.0, min(float(r), (x1 - x0) / 2.0, (y1 - y0) / 2.0))
    spec = [
        ((x0, y0 + r), (x0, y0), (x0 + r, y0), corners[0]),
        ((x1 - r, y0), (x1, y0), (x1, y0 + r), corners[1]),
        ((x1, y1 - r), (x1, y1), (x1 - r, y1), corners[2]),
        ((x0 + r, y1), (x0, y1), (x0, y1 - r), corners[3]),
    ]
    pts = []
    for entry, c, exit_, rounded in spec:
        if rounded:
            pts += [entry[0], entry[1], c[0], c[1], exit_[0], exit_[1]]
        else:
            pts += [c[0], c[1], c[0], c[1], c[0], c[1]]
    return pts


# ── Pinstripe background (the Aqua signature) ─────────────────────────────────
class PinstripeFrame(tk.Canvas):
    """A container canvas painted with fine horizontal Aqua pinstripes.
    Child widgets can be pack()ed straight into it."""

    def __init__(self, parent, **kw):
        kw.setdefault('bg', BG)
        kw.setdefault('highlightthickness', 0)
        tk.Canvas.__init__(self, parent, **kw)
        self._sz = (0, 0)
        self.bind('<Configure>', self._on_cfg)

    def _on_cfg(self, e):
        if (e.width, e.height) != self._sz:
            self._sz = (e.width, e.height)
            self._draw()

    def _draw(self):
        self.delete('stripe')
        w, h = self._sz
        for y in range(0, h, 4):
            self.create_line(0, y, w, y, fill=STRIPE, tags='stripe')
        self.tag_lower('stripe')


# ── Aqua gel button (Canvas-drawn — tk.Button bg is unreliable on macOS) ──────
class AquaButton(tk.Canvas):
    """Classic Aqua gel button / segmented-control segment.

    Supports: .configure(state=..., text=...), .set_selected(bool),
    optional second caption line (sub), and corner control for building
    connected segmented groups ('left' / 'mid' / 'right' / 'all')."""

    PALS = {
        'aqua': dict(border='#3a5e94', base='#2e6bc8', gloss='#6fb0f2',
                     spec='#bcdcfa', fg='#ffffff', fgsh='#1c4583',
                     sub='#dcebfb'),
        'white': dict(border='#9b9b9b', base='#d2d2d2', gloss='#f4f4f4',
                      spec='#fdfdfd', fg='#333333', fgsh='#fafafa',
                      sub='#777777'),
    }
    DISABLED = dict(border='#c4c4c4', base='#e3e3e3', gloss='#f0f0f0',
                    spec='#f7f7f7', fg='#a4a4a4', fgsh='#f0f0f0',
                    sub='#bcbcbc')

    def __init__(self, parent, text='', sub=None, command=None, kind='white',
                 corners='all', selected=False, min_width=0, height=None,
                 font=None, sub_font=None, parent_bg=None):
        self._text     = text
        self._sub      = sub
        self._command  = command
        self._kind     = kind
        self._corners  = corners
        self._selected = selected
        self._state    = 'normal'
        self._hover    = False
        self._press    = False
        self._min_w    = min_width
        self._font     = font or FONTS['button']
        self._sub_font = sub_font or FONTS['micro']
        self._h        = height or (40 if sub else 28)
        pbg = parent_bg or parent.cget('bg')
        tk.Canvas.__init__(self, parent, width=self._calc_w(),
                           height=self._h, bg=pbg,
                           highlightthickness=0, cursor='hand2')
        self.bind('<Enter>', self._on_enter)
        self.bind('<Leave>', self._on_leave)
        self.bind('<ButtonPress-1>', self._on_press)
        self.bind('<ButtonRelease-1>', self._on_release)
        self._render()

    # ── sizing ────────────────────────────────────────────────────────
    def _calc_w(self):
        w = tkfont.Font(font=self._font).measure(self._text) + 30
        if self._sub:
            w = max(w, tkfont.Font(font=self._sub_font).measure(self._sub) + 24)
        return max(w, self._min_w)

    # ── palette ───────────────────────────────────────────────────────
    def _pal(self):
        if self._state == 'disabled':
            return self.DISABLED
        base = (self.PALS['aqua'] if (self._selected or self._kind == 'aqua')
                else self.PALS[self._kind])
        if self._press:
            return dict((k, _shade(v, 0.86) if k in
                         ('border', 'base', 'gloss', 'spec') else v)
                        for k, v in base.items())
        if self._hover:
            return dict((k, _tint(v, 0.16) if k in
                         ('base', 'gloss', 'spec') else v)
                        for k, v in base.items())
        return base

    # ── drawing ───────────────────────────────────────────────────────
    def _render(self):
        self.delete('all')
        w = int(float(self['width']))
        h = self._h
        pal = self._pal()
        cmap = {'all': (1, 1, 1, 1), 'left': (1, 0, 0, 1),
                'right': (0, 1, 1, 0), 'mid': (0, 0, 0, 0)}[self._corners]
        if self._corners == 'all' and not self._sub:
            r = (h - 2) / 2.0          # pill push-button
        else:
            r = 8                       # segmented control
        # gel layers: border → base (dark bottom) → gloss (light top
        # half) → specular strip (the Aqua glass highlight)
        self.create_polygon(_round_rect_pts(1, 1, w - 1, h - 1, r, cmap),
                            fill=pal['border'], outline='', smooth=1)
        self.create_polygon(_round_rect_pts(2, 2, w - 2, h - 2,
                                            max(r - 1, 1), cmap),
                            fill=pal['base'], outline='', smooth=1)
        self.create_polygon(_round_rect_pts(2, 2, w - 2, int(h * 0.52),
                                            max(r - 1, 1),
                                            (cmap[0], cmap[1], 0, 0)),
                            fill=pal['gloss'], outline='', smooth=1)
        self.create_polygon(_round_rect_pts(4, 3, w - 4,
                                            max(6, int(h * 0.30)),
                                            max(r - 2, 1),
                                            (cmap[0], cmap[1], 0, 0)),
                            fill=pal['spec'], outline='', smooth=1)
        # etched text (shadow + face)
        cx = w / 2.0
        if self._sub:
            ty, sy = h * 0.34, h * 0.72
            self.create_text(cx, ty + 1, text=self._text,
                             fill=pal['fgsh'], font=self._font)
            self.create_text(cx, ty, text=self._text,
                             fill=pal['fg'], font=self._font)
            self.create_text(cx, sy, text=self._sub,
                             fill=pal['sub'], font=self._sub_font)
        else:
            cy = h / 2.0
            self.create_text(cx, cy + 1, text=self._text,
                             fill=pal['fgsh'], font=self._font)
            self.create_text(cx, cy, text=self._text,
                             fill=pal['fg'], font=self._font)

    # ── events ────────────────────────────────────────────────────────
    def _on_enter(self, _e):
        if self._state == 'normal':
            self._hover = True
            self._render()

    def _on_leave(self, _e):
        self._hover = self._press = False
        self._render()

    def _on_press(self, _e):
        if self._state == 'normal':
            self._press = True
            self._render()

    def _on_release(self, e):
        if self._press:
            self._press = False
            self._render()
            w = int(float(self['width']))
            if 0 <= e.x <= w and 0 <= e.y <= self._h and self._command:
                self._command()

    # ── public API (mirrors tk.Button enough for the app logic) ───────
    def set_selected(self, sel):
        sel = bool(sel)
        if sel != self._selected:
            self._selected = sel
            self._render()

    def configure(self, cnf=None, **kw):
        if isinstance(cnf, dict):
            kw.update(cnf)
            cnf = None
        state   = kw.pop('state', None)
        text    = kw.pop('text', None)
        command = kw.pop('command', None)
        if command is not None:
            self._command = command
        if text is not None:
            self._text = text
            tk.Canvas.configure(self, width=self._calc_w())
        if state is not None:
            self._state = 'disabled' if str(state) == 'disabled' else 'normal'
            tk.Canvas.configure(
                self, cursor='arrow' if self._state == 'disabled' else 'hand2')
        if kw:
            tk.Canvas.configure(self, **kw)
        if state is not None or text is not None or command is not None:
            self._render()

    config = configure


# ── Aqua progress bar (live fan RPM strips) ───────────────────────────────────
class AquaBar(tk.Canvas):
    def __init__(self, parent, height=14, bg=CARD, **kw):
        tk.Canvas.__init__(self, parent, height=height, bg=bg,
                           highlightthickness=0, **kw)
        self._frac = 0.0
        self._wpx = 0
        self.bind('<Configure>', self._on_cfg)

    def _on_cfg(self, e):
        if abs(e.width - self._wpx) > 1:
            self._wpx = e.width
            self._render()

    def set_frac(self, frac):
        self._frac = max(0.0, min(1.0, frac))
        self._render()

    def _render(self):
        w = self._wpx or int(float(self['width']))
        h = int(float(self['height']))
        if w < 12:
            return
        self.delete('all')
        r = (h - 2) / 2.0
        self.create_polygon(_round_rect_pts(1, 1, w - 1, h - 1, r),
                            fill='#e3e7ec', outline=BORDER, smooth=1)
        fw = (w - 2) * self._frac
        if fw >= h:                       # only draw once wide enough for caps
            x1 = 1 + fw
            self.create_polygon(
                _round_rect_pts(2, 2, x1, h - 2, max(r - 1, 1)),
                fill='#2e6bc8', outline='', smooth=1)
            self.create_polygon(
                _round_rect_pts(2, 2, x1, h // 2, max(r - 1, 1), (1, 1, 0, 0)),
                fill='#7fb8f5', outline='', smooth=1)


# ── Gauge widget ──────────────────────────────────────────────────────────────
class CircleGauge(tk.Canvas):
    """Aqua instrument gauge: chrome bezel, glass face, numbered ticks,
    needle + hub, Monaco digital readout. Fully re-rendered from current
    canvas size, so it scales with the window (grid sticky='nsew')."""
    START = 210    # degrees CCW from 3-o'clock = ~8 o'clock
    SWEEP = -240   # clockwise 240°
    TICKS = 25
    MAJOR = 6      # every Nth tick is a major tick

    def __init__(self, parent, size=180, label='', unit='',
                 min_val=0, max_val=100, bg=CARD, **kw):
        tk.Canvas.__init__(self, parent, width=size, height=size + 26,
                           bg=bg, highlightthickness=0, **kw)
        self.min_val = min_val
        self.max_val = max_val
        self._label = label
        self._unit = unit
        self._value = 0.0
        self._target = 0.0
        self._color = GREEN
        self._anim_running = False
        self._sz = (size, size + 26)
        self._resize_job = None
        self.bind('<Configure>', self._on_resize)
        self.after(50, self._render)

    # ── responsive resize (debounced full re-render) ──────────────────
    def _on_resize(self, e):
        if abs(e.width - self._sz[0]) > 2 or abs(e.height - self._sz[1]) > 2:
            self._sz = (e.width, e.height)
            if self._resize_job is None:
                self._resize_job = self.after_idle(self._do_resize)

    def _do_resize(self):
        self._resize_job = None
        self._render()

    # ── animation (ease-out glide toward target) ──────────────────────
    def set_value(self, value, color=None):
        if color:
            self._color = color
        self._target = float(value)
        if not self._anim_running:
            self._anim_running = True
            self._animate()

    def _animate(self):
        try:
            diff = self._target - self._value
            snap = max((self.max_val - self.min_val) * 0.002, 0.01)
            if abs(diff) <= snap:
                self._value = self._target
                self._render()
                self._anim_running = False
                return
            self._value += diff * 0.30
            self._render()
            self.after(40, self._animate)
        except tk.TclError:        # widget destroyed mid-animation
            self._anim_running = False

    # ── helpers ───────────────────────────────────────────────────────
    def _fmt_tick(self, v):
        if (self.max_val - self.min_val) >= 1500:
            return '{:.1f}k'.format(v / 1000.0).replace('.0k', 'k')
        return '{:.0f}'.format(v)

    # ── full re-render from current size ──────────────────────────────
    def _render(self):
        try:
            w = self.winfo_width()
            h = self.winfo_height()
        except tk.TclError:
            return
        if w <= 1:
            w = int(float(self['width']))
        if h <= 1:
            h = int(float(self['height']))
        if w < 80 or h < 100:
            return
        self.delete('all')

        label_h = max(22, int(h * 0.11))
        d  = min(w, h - label_h)              # gauge diameter incl. bezel
        cx = w / 2.0
        cy = (h - label_h) / 2.0
        R  = d / 2.0 - 2

        # chrome bezel — concentric rings, light catching the top
        for col, inset in [('#8f8f8f', 0), ('#d6d6d6', d * 0.008 + 1),
                           ('#f8f8f8', d * 0.016 + 2),
                           ('#b9bcc0', d * 0.024 + 3)]:
            rr = R - inset
            self.create_oval(cx - rr, cy - rr, cx + rr, cy + rr,
                             fill=col, outline='')
        face_r = R - (d * 0.032 + 4)

        # glass face with radial sheen (lighter toward upper centre)
        self.create_oval(cx - face_r, cy - face_r, cx + face_r, cy + face_r,
                         fill='#e7ebf1', outline='')
        steps = 5
        for i in range(steps):
            t = (i + 1) / float(steps)
            rr  = face_r * (1 - 0.17 * t)
            off = face_r * 0.11 * t
            col = _mix('#e7ebf1', '#ffffff', t * 0.85)
            self.create_oval(cx - rr, cy - rr - off,
                             cx + rr, cy + rr - off, fill=col, outline='')
        # specular arc near the top bezel — glass reflection
        gr = face_r * 0.93
        self.create_arc(cx - gr, cy - gr, cx + gr, cy + gr,
                        start=40, extent=100, style='arc',
                        outline='#ffffff', width=max(1, int(d * 0.012)))

        # ticks + numbers at majors
        range_ = self.max_val - self.min_val or 1
        tick_font = ('Monaco', max(7, int(d * 0.048)))
        for i in range(self.TICKS):
            frac = i / float(self.TICKS - 1)
            a = math.radians(self.START + self.SWEEP * frac)
            major = (i % self.MAJOR == 0)
            r_out = face_r * 0.97
            r_in  = face_r * (0.86 if major else 0.91)
            self.create_line(cx + r_in * math.cos(a), cy - r_in * math.sin(a),
                             cx + r_out * math.cos(a), cy - r_out * math.sin(a),
                             fill='#76808e' if major else '#b6bcc6',
                             width=2 if major else 1)
            if major:
                val = self.min_val + range_ * frac
                nr = face_r * 0.74
                self.create_text(cx + nr * math.cos(a), cy - nr * math.sin(a),
                                 text=self._fmt_tick(val),
                                 fill='#8a93a0', font=tick_font)

        # track + value arc (soft tint halo under a saturated arc)
        arc_r = face_r * 0.58
        aw = max(5, int(d * 0.045))
        box = (cx - arc_r, cy - arc_r, cx + arc_r, cy + arc_r)
        self.create_arc(box, start=self.START, extent=self.SWEEP,
                        outline='#d3d9e0', style='arc', width=aw)
        pct = max(0.0, min(1.0, (self._value - self.min_val) / range_))
        if pct > 0.005:
            ext = self.SWEEP * pct
            self.create_arc(box, start=self.START, extent=ext,
                            outline=_tint(self._color, 0.62),
                            style='arc', width=aw + 4)
            self.create_arc(box, start=self.START, extent=ext,
                            outline=self._color, style='arc', width=aw)

        # needle + chrome hub
        a = math.radians(self.START + self.SWEEP * pct)
        nr = face_r * 0.80
        self.create_line(cx - 0.16 * nr * math.cos(a),
                         cy + 0.16 * nr * math.sin(a),
                         cx + nr * math.cos(a), cy - nr * math.sin(a),
                         fill='#3a4452', width=max(2, int(d * 0.016)),
                         capstyle='round')
        hub = max(4, d * 0.042)
        for col, inset in [('#8f8f8f', 0), ('#ececec', hub * 0.28),
                           ('#b2b6bc', hub * 0.62)]:
            rr = hub - inset
            self.create_oval(cx - rr, cy - rr, cx + rr, cy + rr,
                             fill=col, outline='')

        # digital readout (Monaco) + unit on the face
        vy = cy + face_r * 0.45
        self.create_text(cx, vy, text='{:.0f}'.format(self._value),
                         fill='#2c3340',
                         font=('Monaco', max(12, int(d * 0.125)), 'bold'))
        self.create_text(cx, vy + max(12, d * 0.085), text=self._unit,
                         fill='#8a93a0',
                         font=('Lucida Grande', max(8, int(d * 0.052))))

        # etched label under the dial
        ly = h - label_h / 2.0
        lf = ('Lucida Grande', max(9, int(d * 0.058)), 'bold')
        self.create_text(cx, ly + 1, text=self._label, fill='#ffffff', font=lf)
        self.create_text(cx, ly, text=self._label, fill='#5a5a5a', font=lf)


# ── Card helpers ──────────────────────────────────────────────────────────────
def make_card(parent, padx=16, pady=14):
    """Aqua group box: white body, 1px border, soft shadow line below.
    Returns (outer, body) — pack/grid the outer, put content in the body."""
    holder = tk.Frame(parent, bg=parent.cget('bg'))
    border = tk.Frame(holder, bg=BORDER, padx=1, pady=1)
    border.pack(fill='both', expand=True)
    body = tk.Frame(border, bg=CARD, padx=padx, pady=pady)
    body.pack(fill='both', expand=True)
    tk.Frame(holder, bg=SHADOW, height=1).pack(fill='x')
    return holder, body


def section_header(parent, title, desc=None):
    """Etched section title (+ optional description) with a divider."""
    head = tk.Frame(parent, bg=CARD)
    head.pack(fill='x', anchor='w')
    lbl = tk.Label(head, text=title, bg=CARD, fg='#444444',
                   font=FONTS['header'])
    lbl.pack(anchor='w')
    tk.Frame(parent, bg='#dcdcdc', height=1).pack(fill='x', pady=(4, 0))
    tk.Frame(parent, bg='#fafafa', height=1).pack(fill='x')
    if desc:
        tk.Label(parent, text=desc, bg=CARD, fg=DIM,
                 font=FONTS['label']).pack(anchor='w', pady=(5, 0))


class StatCard(tk.Frame):
    def __init__(self, parent, title, accent=ACCENT, **kw):
        holder = tk.Frame(parent, bg=parent.cget('bg'))
        border = tk.Frame(holder, bg=BORDER, padx=1, pady=1)
        border.pack(fill='both', expand=True)
        tk.Frame(holder, bg=SHADOW, height=1).pack(fill='x')
        tk.Frame.__init__(self, border, bg=CARD, padx=14, pady=10, **kw)
        self.pack(fill='both', expand=True)
        self._outer = holder

        head = tk.Frame(self, bg=CARD)
        head.pack(fill='x')
        dot = tk.Canvas(head, width=9, height=9, bg=CARD,
                        highlightthickness=0)
        dot.create_oval(1, 1, 8, 8, fill=accent,
                        outline=_shade(accent, 0.75))
        dot.pack(side='left')
        tk.Label(head, text=title, bg=CARD, fg=DIM,
                 font=FONTS['caption']).pack(side='left', padx=(5, 0))

        self.val_var = tk.StringVar(value='—')
        self.val_lbl = tk.Label(self, textvariable=self.val_var,
                                bg=CARD, fg=TEXT, font=FONTS['readout'])
        self.val_lbl.pack(anchor='w', pady=(3, 0))
        self.sub_var = tk.StringVar()
        tk.Label(self, textvariable=self.sub_var, bg=CARD, fg=DIM,
                 font=FONTS['micro']).pack(anchor='w')

    def grid_outer(self, **kw):
        self._outer.grid(**kw)

    def pack_outer(self, **kw):
        self._outer.pack(**kw)

    def update(self, value, sub='', color=TEXT):
        self.val_var.set(value)
        self.sub_var.set(sub)
        self.val_lbl.configure(fg=color)


# ── Main application ──────────────────────────────────────────────────────────
def _set_dock_icon():
    """Set the Dock icon to FanCooler's fan icon (overrides Python default)."""
    try:
        from AppKit import NSApplication, NSImage
        icns = os.path.expanduser(
            os.path.join(os.path.dirname(os.path.abspath(__file__)), 'AppIcon.icns'))
        icon = NSImage.alloc().initWithContentsOfFile_(icns)
        if icon:
            NSApplication.sharedApplication().setApplicationIconImage_(icon)
    except Exception:
        pass


class DashboardApp:
    HDR_H = 50           # brushed-metal header height

    def __init__(self):
        self.root = tk.Tk()
        self.root.title('FanCooler')
        self.root.geometry('900x640')
        self.root.configure(bg=BG)
        self.root.resizable(True, True)
        self.root.minsize(760, 560)

        self.monitor = SystemMonitor()
        self._cfg = load_config()
        self.temp_alert_var = tk.DoubleVar(
            value=self._cfg.get('alert_temp', 80.0))
        self.alert_enabled = tk.BooleanVar(
            value=self._cfg.get('alert_enabled', True))
        self.monitor.on_high_temp = (
            self._on_high_temp if self.alert_enabled.get() else None)
        self.monitor.temp_alert = self.temp_alert_var.get()

        self._tick = 0
        self._build_ui()
        self.monitor.start()
        self._start_menubar()
        _set_dock_icon()
        self.root.after(800, _set_dock_icon)   # re-apply after Tk fully settles
        self._update_loop()

    def _start_menubar(self):
        """Launch menubar.py as a background process (no Dock icon)."""
        import threading as _th
        def _launch():
            import time; time.sleep(1)   # let main window open first
            try:
                import rumps  # noqa — check it's installed
                _here = os.path.dirname(os.path.abspath(__file__))
                self._menubar_proc = subprocess.Popen(
                    [sys.executable, os.path.join(_here, 'menubar.py')],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            except ImportError:
                pass
            except Exception:
                pass
        _th.Thread(target=_launch, daemon=True).start()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        # Brushed-metal header with etched title + live status at right
        hdr = tk.Canvas(self.root, height=self.HDR_H, bg='#c8c8c8',
                        highlightthickness=0)
        hdr.pack(fill='x')
        self._hdr = hdr

        status = tk.Frame(hdr, bg='#c8c8c8')
        self._pulse_dot = tk.Canvas(status, width=10, height=10,
                                    bg='#c8c8c8', highlightthickness=0)
        self._pulse_item = self._pulse_dot.create_oval(
            2, 2, 8, 8, fill=GREEN, outline=_shade(GREEN, 0.7))
        self._pulse_dot.pack(side='left')
        self.status_lbl = tk.Label(status, text=' Monitoring',
                                   bg='#c8c8c8', fg='#2e7d3c',
                                   font=FONTS['label'])
        self.status_lbl.pack(side='left')
        self._hdr_status_win = hdr.create_window(0, 0, window=status,
                                                 anchor='e')
        hdr.bind('<Configure>', self._draw_header)
        self._pulse_on = True
        self._pulse()

        # Segmented tab bar strip (classic toolbar look)
        strip = tk.Frame(self.root, bg='#c3c3c3')
        strip.pack(fill='x')
        tk.Frame(strip, bg='#dadada', height=1).pack(fill='x')
        tk.Frame(strip, bg='#8e8e8e', height=1).pack(fill='x', side='bottom')
        seg_holder = tk.Frame(strip, bg='#c3c3c3')
        seg_holder.pack(pady=6)

        tabs = [('Dashboard', 'dash'), ('History', 'graph'),
                ('Fan Control', 'fan'), ('Settings', 'set')]
        self._tab_btns = {}
        for i, (label, key) in enumerate(tabs):
            corners = ('left' if i == 0 else
                       ('right' if i == len(tabs) - 1 else 'mid'))
            b = AquaButton(seg_holder, text=label, kind='white',
                           corners=corners, height=24, min_width=108,
                           font=FONTS['tab'], parent_bg='#c3c3c3',
                           command=lambda k=key: self._select_tab(k))
            b.pack(side='left')
            self._tab_btns[key] = b

        # Tab container — frames stacked in one grid cell, raised on select
        self._tab_container = tk.Frame(self.root, bg=BG)
        self._tab_container.pack(fill='both', expand=True)
        self._tab_container.rowconfigure(0, weight=1)
        self._tab_container.columnconfigure(0, weight=1)
        self._tabs = {}

        self._build_dashboard_tab()
        self._build_graph_tab()
        self._build_fanctrl_tab()
        self._build_settings_tab()
        self._select_tab('dash')

    def _draw_header(self, _event=None):
        """Brushed-metal vertical gradient + etched 'FanCooler' title."""
        c = self._hdr
        w = max(c.winfo_width(), 1)
        h = self.HDR_H
        c.delete('hdr')
        for y in range(h):
            c.create_line(0, y, w, y,
                          fill=_mix('#dedede', '#b2b2b2', y / float(h)),
                          tags='hdr')
        c.create_line(0, 0, w, 0, fill='#f4f4f4', tags='hdr')
        c.create_line(0, h - 1, w, h - 1, fill='#8a8a8a', tags='hdr')
        cy = h // 2
        c.create_text(21, cy + 1, text='FanCooler', anchor='w',
                      fill='#ffffff', font=FONTS['brand'], tags='hdr')
        c.create_text(20, cy, text='FanCooler', anchor='w',
                      fill='#3c3c3c', font=FONTS['brand'], tags='hdr')
        c.create_text(132, cy + 2, text='Thermal control', anchor='w',
                      fill='#6e6e6e', font=FONTS['micro'], tags='hdr')
        c.tag_lower('hdr')
        c.coords(self._hdr_status_win, w - 16, cy)

    def _select_tab(self, key):
        for k, b in self._tab_btns.items():
            b.set_selected(k == key)
        frame = self._tabs[key]
        # tk.Misc.tkraise, not frame.tkraise(): on Canvas-based tabs
        # (PinstripeFrame) tkraise is remapped to canvas-item raising.
        tk.Misc.tkraise(frame)
        self._current_tab = frame
        if key == 'graph' and HAS_MPL and hasattr(self, 'mpl_canvas'):
            try:
                self._update_graphs(self.monitor.get_history())
            except Exception:
                pass

    def _pulse(self):
        """Blink the header status dot — 'alive' indicator."""
        try:
            self._pulse_on = not self._pulse_on
            self._pulse_dot.itemconfigure(
                self._pulse_item,
                fill=GREEN if self._pulse_on else '#9dbda6')
            self.root.after(700, self._pulse)
        except tk.TclError:
            pass

    def _build_dashboard_tab(self):
        tab = PinstripeFrame(self._tab_container)
        tab.grid(row=0, column=0, sticky='nsew')
        self._tab_dash = tab
        self._tabs['dash'] = tab

        # Gauges — in one white panel that grows with the window; each
        # gauge cell has weight so the dials scale responsively.
        g_outer, g_body = make_card(tab, padx=8, pady=8)
        g_outer.pack(fill='both', expand=True, padx=20, pady=(16, 8))
        g_body.columnconfigure((0, 1, 2, 3), weight=1, uniform='g')
        g_body.rowconfigure(0, weight=1)

        self.g_cpu  = CircleGauge(g_body, label='CPU Usage',   unit='%',   min_val=0, max_val=100)
        self.g_temp = CircleGauge(g_body, label='Temperature', unit='°C',  min_val=0, max_val=100)
        self.g_fan  = CircleGauge(g_body, label='Fan Speed',   unit='RPM', min_val=0, max_val=6000)
        self.g_mem  = CircleGauge(g_body, label='Memory',      unit='%',   min_val=0, max_val=100)

        for col, g in enumerate((self.g_cpu, self.g_temp, self.g_fan, self.g_mem)):
            g.grid(row=0, column=col, sticky='nsew', padx=4, pady=4)

        # Stat cards — secondary detail row (fixed height)
        cards = tk.Frame(tab, bg=BG)
        cards.pack(fill='x', padx=20, pady=(0, 12))
        cards.columnconfigure((0, 1, 2, 3), weight=1, uniform='c')

        self.c_freq = StatCard(cards, 'CPU Frequency', accent=ACCENT)
        self.c_freq.grid_outer(row=0, column=0, sticky='nsew', padx=(0, 8))

        self.c_temp = StatCard(cards, 'Temperature', accent=ORANGE)
        self.c_temp.grid_outer(row=0, column=1, sticky='nsew', padx=(0, 8))

        self.c_fan = StatCard(cards, 'Fan Speed', accent=BLUE)
        self.c_fan.grid_outer(row=0, column=2, sticky='nsew', padx=(0, 8))

        self.c_mem = StatCard(cards, 'Memory Used', accent=GREEN)
        self.c_mem.grid_outer(row=0, column=3, sticky='nsew')

        # Footer info bar (classic status bar)
        foot = tk.Frame(tab, bg='#dcdcdc')
        foot.pack(fill='x', side='bottom')
        tk.Frame(foot, bg='#a8a8a8', height=1).pack(fill='x')
        self.info_lbl = tk.Label(foot, text='', bg='#dcdcdc', fg='#666666',
                                 font=FONTS['label'], anchor='w',
                                 padx=14, pady=5)
        self.info_lbl.pack(fill='x')

    def _build_graph_tab(self):
        tab = tk.Frame(self._tab_container, bg=BG)
        tab.grid(row=0, column=0, sticky='nsew')
        self._tab_graph = tab
        self._tabs['graph'] = tab

        if not HAS_MPL:
            tk.Label(tab,
                     text='matplotlib not installed.\n\nRun:  pip install matplotlib',
                     bg=BG, fg=DIM, font=FONTS['body']).pack(expand=True)
            return

        matplotlib.rcParams.update({
            'font.family':      'sans-serif',
            'font.sans-serif':  ['Lucida Grande', 'Helvetica Neue',
                                 'Helvetica', 'Arial'],
            'axes.facecolor':   '#ffffff',
            'figure.facecolor': BG,
            'axes.edgecolor':   '#c8c8c8',
            'axes.labelcolor':  '#666666',
            'xtick.color':      '#777777',
            'ytick.color':      '#777777',
            'grid.color':       '#d0d8e0',
            'text.color':       '#333333',
        })

        self.fig = Figure(figsize=(8, 4.8), dpi=96, facecolor=BG)
        self.fig.subplots_adjust(hspace=0.52, left=0.08,
                                 right=0.98, top=0.93, bottom=0.10)

        self.ax_cpu  = self.fig.add_subplot(3, 1, 1)
        self.ax_temp = self.fig.add_subplot(3, 1, 2)
        self.ax_fan  = self.fig.add_subplot(3, 1, 3)

        fan_top = 6500
        fans = self.monitor.fan_ctrl.get_fan_info()
        if fans:
            fan_top = max(f[2] for f in fans) + 300

        graph_specs = [
            (self.ax_cpu,  'CPU load (%)',      (0, 100),     ACCENT),
            (self.ax_temp, 'Temperature (°C)',  None,         ORANGE),
            (self.ax_fan,  'Fan speed (RPM)',   (0, fan_top), TEAL),
        ]
        self._graph_lines = []
        self._graph_fills = []
        self._graph_axes  = []
        self._graph_marks = []
        for ax, label, ylim, color in graph_specs:
            ax.set_facecolor('#ffffff')
            ax.grid(True, axis='y', color='#d0d8e0',     # soft Aqua grid
                    linewidth=0.7, alpha=0.9)
            ax.set_axisbelow(True)
            ax.spines['top'].set_visible(False)          # no chartjunk
            ax.spines['right'].set_visible(False)
            ax.spines['left'].set_color('#c0c0c0')
            ax.spines['bottom'].set_color('#c0c0c0')
            ax.tick_params(colors='#777777', labelsize=7, length=0)
            if ax is not self.ax_fan:                    # shared time axis —
                ax.tick_params(labelbottom=False)        # only bottom has labels
            ax.set_title(label, loc='left', fontsize=9,
                         color='#4a4a4a', fontweight='bold', pad=4)
            if ylim:
                ax.set_ylim(*ylim)
            line, = ax.plot([], [], color=color, linewidth=2.0,
                            solid_capstyle='round', animated=False, zorder=4)
            # latest-point marker + value badge
            mark, = ax.plot([], [], marker='o', ms=5, ls='',
                            mfc='#ffffff', mec=color, mew=1.5, zorder=5)
            ann = ax.annotate('', xy=(0, 0), xytext=(-10, 8),
                              textcoords='offset points', ha='right',
                              fontsize=8, color='#333333', zorder=6,
                              bbox=dict(boxstyle='round,pad=0.3',
                                        fc='#ffffff', ec='#b8c4d4'))
            ann.set_visible(False)
            self._graph_lines.append(line)
            self._graph_fills.append((ax, color))
            self._graph_axes.append((ax, ylim))
            self._graph_marks.append((mark, ann))
        self.ax_fan.set_xlabel('seconds (1 sample/s)', fontsize=7,
                               color='#777777')

        # Alert line on temp graph (static)
        self._alert_line = self.ax_temp.axhline(
            y=80, color=RED, linestyle=(0, (4, 4)), alpha=0.5, linewidth=1)

        self.mpl_canvas = FigureCanvasTkAgg(self.fig, master=tab)
        self.mpl_canvas.draw()
        self.mpl_canvas.get_tk_widget().pack(fill='both', expand=True,
                                             padx=16, pady=12)

    def _build_fanctrl_tab(self):
        fc = self.monitor.fan_ctrl          # shorthand
        tab = tk.Frame(self._tab_container, bg=BG)
        tab.grid(row=0, column=0, sticky='nsew')
        self._tab_fan = tab
        self._tabs['fan'] = tab

        canvas = tk.Canvas(tab, bg=BG, highlightthickness=0)
        scroll = tk.Scrollbar(tab, orient='vertical', command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        canvas.pack(side='left', fill='both', expand=True)
        inner = tk.Frame(canvas, bg=BG)
        win_id = canvas.create_window((0, 0), window=inner, anchor='nw')
        inner.bind('<Configure>',
                   lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>',
                    lambda e: canvas.itemconfig(win_id, width=e.width))

        PADX = 20

        # ── (1) Live fan status strip ──────────────────────────────
        st_outer, st = make_card(inner)
        st_outer.pack(fill='x', padx=PADX, pady=(16, 6))
        section_header(st, 'Live fan status')

        self._fc_fan_rows = []
        fans = fc.get_fan_info()
        fgrid = tk.Frame(st, bg=CARD)
        fgrid.pack(fill='x', pady=(10, 2))
        fgrid.columnconfigure(2, weight=1)
        for i, (cur, _mn, mx) in enumerate(fans):
            if len(fans) == 2:
                name = 'Left fan' if i == 0 else 'Right fan'
            else:
                name = 'Fan {}'.format(i + 1)
            tk.Label(fgrid, text=name, bg=CARD, fg=TEXT, anchor='w',
                     width=10, font=FONTS['body']).grid(
                row=i, column=0, sticky='w', pady=3)
            rpm_lbl = tk.Label(fgrid, text='{:>5,} RPM'.format(cur),
                               bg=CARD, fg=ACCENT, anchor='e', width=10,
                               font=FONTS['big_value'])
            rpm_lbl.grid(row=i, column=1, sticky='w', padx=(8, 0), pady=3)
            bar = AquaBar(fgrid)
            bar.grid(row=i, column=2, sticky='ew', padx=(14, 2), pady=3)
            bar.set_frac(cur / float(mx or 1))
            self._fc_fan_rows.append((rpm_lbl, bar, mx))
        if not fans:
            tk.Label(fgrid, text='No fan telemetry — smc_tool unavailable.',
                     bg=CARD, fg=RED, font=FONTS['label']).grid(
                row=0, column=0, sticky='w', pady=2)

        tk.Frame(st, bg='#e4e4e4', height=1).pack(fill='x', pady=(8, 6))
        srow = tk.Frame(st, bg=CARD)
        srow.pack(fill='x')
        tk.Label(srow, text='Mode', bg=CARD, fg=DIM, width=6, anchor='w',
                 font=FONTS['caption']).pack(side='left')
        self.fc_mode_lbl = tk.Label(srow, text='Mode: Auto', bg=CARD,
                                    fg=TEXT, font=FONTS['value'])
        self.fc_mode_lbl.pack(side='left')
        if fc.available:
            tool_txt = 'smc_tool ready ({} fans)'.format(fc.num_fans)
            tool_clr = GREEN
        else:
            tool_txt = 'smc_tool not found'
            tool_clr = RED
        self.fc_tool_lbl = tk.Label(srow, text=tool_txt, bg=CARD,
                                    fg=tool_clr, font=FONTS['micro'])
        self.fc_tool_lbl.pack(side='right')
        self.fc_status_lbl = tk.Label(st, text='', bg=CARD, fg=ACCENT,
                                      font=FONTS['label'])
        self.fc_status_lbl.pack(anchor='w', pady=(4, 0))

        # ── One-time setup: yellow banner (or green check when done) ──
        if fc.is_setup:
            self.fc_setup_btn = None
            self.fc_sudo_lbl = tk.Label(
                st, text='✓ Password-free fan control is set up',
                bg=CARD, fg=GREEN, font=FONTS['label'])
            self.fc_sudo_lbl.pack(anchor='w', pady=(2, 0))
        else:
            ban_holder = tk.Frame(inner, bg='#cdaa4e', padx=1, pady=1)
            ban_holder.pack(fill='x', padx=PADX, pady=6)
            ban = tk.Frame(ban_holder, bg='#fdf3cf', padx=14, pady=10)
            ban.pack(fill='both')
            tk.Label(ban, text='⚠  One-time setup required',
                     bg='#fdf3cf', fg='#7a5b12',
                     font=('Lucida Grande', 12, 'bold')).pack(anchor='w')
            brow = tk.Frame(ban, bg='#fdf3cf')
            brow.pack(fill='x', pady=(6, 0))
            self.fc_sudo_lbl = tk.Label(brow,
                                        text='Password required each time',
                                        bg='#fdf3cf', fg='#8a6d1d',
                                        font=FONTS['label'])
            self.fc_sudo_lbl.pack(side='left')
            self.fc_setup_btn = AquaButton(
                brow, text='Set Up Now…', kind='aqua',
                parent_bg='#fdf3cf', command=self._fc_do_setup)
            self.fc_setup_btn.pack(side='left', padx=(14, 0))
            tk.Label(brow, text='  asks for your password once, then never again',
                     bg='#fdf3cf', fg='#a08838',
                     font=FONTS['micro']).pack(side='left')

        # ── (2+3) Fan mode + custom RPM ────────────────────────────
        mode_outer, mode_card = make_card(inner)
        mode_outer.pack(fill='x', padx=PADX, pady=6)
        section_header(mode_card, 'Fan mode',
                       'Pick a preset — "Auto" hands control back to macOS.')

        seg = tk.Frame(mode_card, bg=CARD)
        seg.pack(anchor='w', pady=(12, 2))
        self._preset_btns = {}
        presets = [('Auto', 0), ('Eco', 1200), ('Normal', 2500),
                   ('Performance', 4000), ('Max', 6200)]
        for i, (name, rpm) in enumerate(presets):
            corners = ('left' if i == 0 else
                       ('right' if i == len(presets) - 1 else 'mid'))
            sub = 'system' if rpm == 0 else '{:,} RPM'.format(rpm)
            btn = AquaButton(
                seg, text=name, sub=sub, kind='white', corners=corners,
                height=40, min_width=106,
                font=('Lucida Grande', 12, 'bold'), parent_bg=CARD,
                command=lambda n=name: self._fc_choose_preset(n))
            btn.pack(side='left')
            self._preset_btns[name] = btn
        self._preset_btns['Auto'].set_selected(True)

        tk.Frame(mode_card, bg='#e4e4e4', height=1).pack(fill='x',
                                                         pady=(14, 8))

        mgrid = tk.Frame(mode_card, bg=CARD)
        mgrid.pack(fill='x')
        mgrid.columnconfigure(1, weight=1)
        tk.Label(mgrid, text='Custom minimum', bg=CARD, fg=TEXT,
                 font=FONTS['body']).grid(row=0, column=0, sticky='w')
        self.fc_man_rpm_var = tk.IntVar(
            value=self._cfg.get('manual_rpm', 2500))
        tk.Scale(mgrid, from_=0, to=6200, variable=self.fc_man_rpm_var,
                 orient='horizontal', bg=CARD, fg=TEXT,
                 troughcolor='#dde3ea', highlightthickness=0, bd=0,
                 showvalue=0, resolution=100,
                 activebackground=ACCENT).grid(
            row=0, column=1, sticky='ew', padx=(14, 14), pady=4)
        self.fc_man_rpm_lbl = tk.Label(
            mgrid, text='{:>4d} RPM'.format(self.fc_man_rpm_var.get()),
            bg=CARD, fg=ACCENT, font=FONTS['big_value'],
            width=9, anchor='e')
        self.fc_man_rpm_lbl.grid(row=0, column=2, sticky='e')
        self.fc_man_rpm_var.trace('w', self._fc_update_man_lbl)

        btn_row = tk.Frame(mode_card, bg=CARD)
        btn_row.pack(anchor='w', pady=(12, 0))
        self.fc_apply_btn = AquaButton(
            btn_row, text='Apply', kind='aqua', min_width=96,
            parent_bg=CARD, command=self._fc_apply_manual)
        self.fc_apply_btn.pack(side='left', padx=(0, 8))
        self.fc_reset_btn = AquaButton(
            btn_row, text='Reset to Auto', kind='white',
            parent_bg=CARD, command=self._fc_reset)
        self.fc_reset_btn.pack(side='left')

        # ── (4) Auto-boost section ─────────────────────────────────
        boost_outer, boost_card = make_card(inner)
        boost_outer.pack(fill='x', padx=PADX, pady=6)
        section_header(boost_card, 'Auto-boost',
                       'Automatically raise fan speed when temperature is high.')

        self.fc_auto_var = tk.BooleanVar(
            value=self._cfg.get('auto_boost', False))
        tk.Checkbutton(boost_card, text='Enable auto-boost',
                       variable=self.fc_auto_var, bg=CARD, fg=TEXT,
                       selectcolor='#ffffff', activebackground=CARD,
                       activeforeground=TEXT, highlightthickness=0,
                       font=FONTS['body'],
                       command=self._fc_apply_auto).pack(anchor='w',
                                                         pady=(8, 0))

        bgrid = tk.Frame(boost_card, bg=CARD)
        bgrid.pack(fill='x', pady=(6, 0))
        bgrid.columnconfigure(1, weight=1)

        tk.Label(bgrid, text='Trigger above', bg=CARD, fg=TEXT,
                 font=FONTS['body']).grid(row=0, column=0, sticky='w')
        self.fc_thresh_var = tk.DoubleVar(
            value=self._cfg.get('boost_thresh', 75.0))
        tk.Scale(bgrid, from_=55, to=90, variable=self.fc_thresh_var,
                 orient='horizontal', bg=CARD, fg=TEXT,
                 troughcolor='#dde3ea', highlightthickness=0, bd=0,
                 showvalue=0, activebackground=ORANGE,
                 command=self._fc_apply_auto).grid(
            row=0, column=1, sticky='ew', padx=(14, 14), pady=4)
        self.fc_thresh_lbl = tk.Label(bgrid, text=' 75°C', bg=CARD,
                                      fg=ORANGE, font=FONTS['big_value'],
                                      width=9, anchor='e')
        self.fc_thresh_lbl.grid(row=0, column=2, sticky='e')

        tk.Label(bgrid, text='Boost to', bg=CARD, fg=TEXT,
                 font=FONTS['body']).grid(row=1, column=0, sticky='w')
        self.fc_boost_rpm_var = tk.IntVar(
            value=self._cfg.get('boost_rpm', 4000))
        tk.Scale(bgrid, from_=1200, to=6200, variable=self.fc_boost_rpm_var,
                 orient='horizontal', bg=CARD, fg=TEXT,
                 troughcolor='#dde3ea', highlightthickness=0, bd=0,
                 showvalue=0, activebackground=BLUE, resolution=100,
                 command=self._fc_apply_auto).grid(
            row=1, column=1, sticky='ew', padx=(14, 14), pady=4)
        self.fc_boost_rpm_lbl = tk.Label(bgrid, text='4000 RPM', bg=CARD,
                                         fg=BLUE, font=FONTS['big_value'],
                                         width=9, anchor='e')
        self.fc_boost_rpm_lbl.grid(row=1, column=2, sticky='e')

        # ── Status note when tool missing ──────────────────────────
        if not fc.available:
            note_outer, note = make_card(inner)
            note_outer.pack(fill='x', padx=PADX, pady=6)
            tk.Label(note,
                     text='smc_tool not found in app directory.',
                     bg=CARD, fg=RED, font=FONTS['body']).pack(anchor='w')
            tk.Label(note,
                     text='Re-clone the repo or copy smc_tool next to dashboard.py.',
                     bg=CARD, fg=DIM, font=FONTS['label']).pack(anchor='w', pady=(4, 0))

        tk.Frame(inner, bg=BG, height=16).pack()   # bottom padding

        # Push loaded config into the controller and sync labels
        self._fc_apply_auto()

        # Disable controls if tool not available
        if not fc.available:
            self._fc_set_controls_state('disabled')

    def _build_settings_tab(self):
        tab = PinstripeFrame(self._tab_container)
        tab.grid(row=0, column=0, sticky='nsew')
        self._tabs['set'] = tab

        inner = tk.Frame(tab, bg=BG)
        inner.pack(fill='x', padx=20, pady=16, anchor='nw')

        # Alert section
        alert_outer, alert_card = make_card(inner)
        alert_outer.pack(fill='x', pady=(0, 12))
        section_header(alert_card, 'Temperature alerts',
                       'Get a macOS notification when the CPU runs hot.')

        tk.Checkbutton(alert_card,
                       text='Enable alerts when temperature exceeds threshold',
                       variable=self.alert_enabled, bg=CARD, fg=TEXT,
                       selectcolor='#ffffff', activebackground=CARD,
                       activeforeground=TEXT, highlightthickness=0,
                       font=FONTS['body'],
                       command=self._apply_alert_settings).pack(anchor='w',
                                                                pady=(8, 0))

        agrid = tk.Frame(alert_card, bg=CARD)
        agrid.pack(fill='x', pady=(6, 0))
        agrid.columnconfigure(1, weight=1)
        tk.Label(agrid, text='Alert at', bg=CARD, fg=TEXT,
                 font=FONTS['body']).grid(row=0, column=0, sticky='w')
        self.alert_scale = tk.Scale(
            agrid, from_=50, to=100, variable=self.temp_alert_var,
            orient='horizontal', bg=CARD, fg=TEXT,
            troughcolor='#dde3ea', highlightthickness=0, bd=0,
            showvalue=0,
            activebackground=ACCENT, command=self._apply_alert_settings)
        self.alert_scale.grid(row=0, column=1, sticky='ew',
                              padx=(14, 14), pady=4)
        self.alert_val_lbl = tk.Label(agrid, text=' 80°C', bg=CARD,
                                      fg=ORANGE, font=FONTS['big_value'],
                                      width=9, anchor='e')
        self.alert_val_lbl.grid(row=0, column=2, sticky='e')

        # System info section
        info_outer, info_card = make_card(inner)
        info_outer.pack(fill='x')
        section_header(info_card, 'System info')
        self.sys_info_lbl = tk.Label(info_card, text='', bg=CARD,
                                     fg='#4a4a4a', font=FONTS['value'],
                                     justify='left')
        self.sys_info_lbl.pack(anchor='w', pady=(8, 0))
        self._refresh_sys_info()

    # ── Settings persistence ──────────────────────────────────────────────────

    def _save_cfg(self):
        if not hasattr(self, 'fc_man_rpm_var'):
            return   # UI not fully built yet
        save_config({
            'alert_enabled': bool(self.alert_enabled.get()),
            'alert_temp':    float(self.temp_alert_var.get()),
            'auto_boost':    bool(self.fc_auto_var.get()),
            'boost_thresh':  float(self.fc_thresh_var.get()),
            'boost_rpm':     int(self.fc_boost_rpm_var.get()),
            'manual_rpm':    int(self.fc_man_rpm_var.get()),
        })

    # ── Fan Control logic ─────────────────────────────────────────────────────

    def _fc_choose_preset(self, name):
        """Visual segment selection, then the existing preset logic."""
        for n, b in self._preset_btns.items():
            b.set_selected(n == name)
        self._fc_preset(name)

    def _fc_set_controls_state(self, state):
        """Enable or disable all fan control interactive widgets."""
        for w in [self.fc_man_rpm_var]:
            pass  # StringVar — skip
        try:
            for btn in self._preset_btns.values():
                btn.configure(state=state)
        except Exception:
            pass

    def _fc_apply_auto(self, *_):
        fc = self.monitor.fan_ctrl
        fc.auto_boost   = self.fc_auto_var.get()
        fc.boost_thresh = self.fc_thresh_var.get()
        fc.boost_rpm    = self.fc_boost_rpm_var.get()
        self.fc_thresh_lbl.configure(
            text='{:>3.0f}°C'.format(fc.boost_thresh))
        self.fc_boost_rpm_lbl.configure(
            text='{:>4d} RPM'.format(int(fc.boost_rpm)))
        self._save_cfg()

    def _fc_update_man_lbl(self, *_):
        self.fc_man_rpm_lbl.configure(
            text='{:>4d} RPM'.format(self.fc_man_rpm_var.get()))

    def _fc_run_async(self, fn, on_success_msg, on_success_mode=None):
        """Run a fan control function in a background thread.
        Shows 'Waiting for password...' while macOS dialog is open,
        then updates status label when done — keeps UI responsive.
        """
        import threading as _th
        if not self.monitor.fan_ctrl.available:
            self._fc_show_status('smc_tool not found in app folder', RED)
            return

        if self.monitor.fan_ctrl.is_setup:
            self._fc_show_status('Applying...', ACCENT)
        else:
            self._fc_show_status('Waiting for password...', YELLOW)
        self._fc_set_buttons_state('disabled')

        def _worker():
            ok, msg = fn()
            def _done():
                self._fc_set_buttons_state('normal')
                if ok:
                    self._fc_show_status(on_success_msg, GREEN)
                    if on_success_mode:
                        try:
                            self.fc_mode_lbl.configure(text=on_success_mode)
                        except Exception:
                            pass
                else:
                    err = msg.strip() if msg else 'Auth cancelled'
                    self._fc_show_status(err[:60] or 'Cancelled', RED)
            self.root.after(0, _done)

        _th.Thread(target=_worker, daemon=True).start()

    def _fc_set_buttons_state(self, state):
        for btn in self._preset_btns.values():
            try:
                btn.configure(state=state)
            except Exception:
                pass
        for btn in [self.fc_apply_btn, self.fc_reset_btn]:
            try:
                btn.configure(state=state)
            except Exception:
                pass

    def _fc_preset(self, name):
        fc = self.monitor.fan_ctrl
        mode = 'Mode: Auto' if name == 'Auto' else 'Mode: {} preset'.format(name)
        self._fc_run_async(
            lambda: fc.apply_preset(name),
            on_success_msg='Preset applied: {}'.format(name),
            on_success_mode=mode,
        )

    def _fc_apply_manual(self):
        rpm = self.fc_man_rpm_var.get()
        fc = self.monitor.fan_ctrl
        self._save_cfg()
        self._fc_run_async(
            lambda: fc.set_min_rpm(rpm),
            on_success_msg='Min fan set to {} RPM'.format(rpm),
            on_success_mode='Mode: Manual ({} RPM min)'.format(rpm),
        )

    def _fc_reset(self):
        fc = self.monitor.fan_ctrl
        self._fc_run_async(
            lambda: fc.reset_auto(),
            on_success_msg='Fan reset to Auto (macOS controls)',
            on_success_mode='Mode: Auto',
        )

    def _fc_show_status(self, msg, color=ACCENT):
        try:
            self.fc_status_lbl.configure(text=msg, fg=color)
        except Exception:
            pass

    def _fc_do_setup(self):
        """Run the one-time sudoers setup (shows macOS password dialog once)."""
        fc = self.monitor.fan_ctrl
        if self.fc_setup_btn:
            self.fc_setup_btn.configure(state='disabled', text='Setting up...')
        self.fc_sudo_lbl.configure(text='Asking for password...', fg=YELLOW)

        def _on_done(ok, msg):
            def _update():
                if ok:
                    self.fc_sudo_lbl.configure(
                        text='✓ No password needed', fg=GREEN)
                    if self.fc_setup_btn:
                        self.fc_setup_btn.pack_forget()
                        self.fc_setup_btn = None
                    self._fc_show_status('Setup complete — no more password dialogs!', GREEN)
                else:
                    self.fc_sudo_lbl.configure(
                        text='Setup failed or cancelled', fg=RED)
                    if self.fc_setup_btn:
                        self.fc_setup_btn.configure(state='normal', text='Retry Setup')
                    self._fc_show_status('Setup failed: ' + (msg[:50] if msg else ''), RED)
            self.root.after(0, _update)

        fc.setup_sudoers(on_done=_on_done)

    def _fc_update_loop(self):
        """Update fan control status label + live fan strips from monitor."""
        fc = self.monitor.fan_ctrl
        try:
            data = self.monitor.get_current()
            fans = data.get('fans') or []
            for i, (lbl, bar, mx) in enumerate(self._fc_fan_rows):
                if i < len(fans):
                    cur = fans[i][0]
                    fmax = fans[i][2] or mx or 1
                    lbl.configure(text='{:>5,} RPM'.format(cur))
                    bar.set_frac(cur / float(fmax))
        except Exception:
            pass
        try:
            if fc._boosted:
                self.fc_mode_lbl.configure(
                    text='Mode: Auto-Boosted ({} RPM)'.format(fc.boost_rpm))
            elif fc.auto_boost:
                self.fc_mode_lbl.configure(text='Mode: Auto-Boost (watching)')
            with fc._lock:
                msg = fc.status_msg
            if msg:
                self.fc_status_lbl.configure(text=msg)
        except Exception:
            pass

    # ── Logic ─────────────────────────────────────────────────────────────────

    def _refresh_sys_info(self):
        try:
            phys = psutil.cpu_count(logical=False)
            logi = psutil.cpu_count(logical=True)
            mem  = psutil.virtual_memory()
            gb   = mem.total / 1024 ** 3
            mac_ver = platform.mac_ver()[0] or platform.system()
            self.sys_info_lbl.configure(
                text=f'macOS: {mac_ver}\n'
                     f'CPU: {phys} cores physical, {logi} logical\n'
                     f'Memory: {gb:.1f} GB total\n'
                     f'Python: {platform.python_version()}'
            )
        except Exception as e:
            self.sys_info_lbl.configure(text=f'Error: {e}')

    def _apply_alert_settings(self, *_):
        val = self.temp_alert_var.get()
        self.alert_val_lbl.configure(text='{:>3.0f}°C'.format(val))
        self.monitor.temp_alert = val
        self.monitor.on_high_temp = self._on_high_temp if self.alert_enabled.get() else None
        self._save_cfg()

    def _on_high_temp(self, temp):
        self.root.after(0, lambda: self._show_alert(temp))

    def _show_alert(self, temp):
        try:
            subprocess.run([
                'osascript', '-e',
                'display notification "Temperature: {:.1f}C -- above alert threshold!" '
                'with title "FanCooler Alert" sound name "Glass"'.format(temp)
            ], timeout=3, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except Exception:
            pass
        messagebox.showwarning(
            'Temperature Alert',
            f'CPU temperature reached {temp:.1f}°C!\nConsider reducing workload.')

    # ── Update loop ───────────────────────────────────────────────────────────

    def _update_loop(self):
        data = self.monitor.get_current()
        hist = self.monitor.get_history()

        tc = temp_color(data['temp'])
        fc = fan_color(data['fan'] / max(data['fan_max'], 1) * 100)

        self.g_cpu.set_value(data['cpu'], ACCENT)
        self.g_temp.set_value(data['temp'], tc)
        self.g_fan.max_val = max(data['fan_max'], 1)   # actual hw max
        self.g_fan.set_value(data['fan'], fc)
        self.g_mem.set_value(data['mem'], ACCENT)

        # Padded numerals so the readouts don't jitter as digits change
        self.c_freq.update(f"{data['cpu_freq']:>4.0f} MHz",
                           f"CPU load: {data['cpu']:>4.1f}%")
        self.c_temp.update(f"{data['temp']:>5.1f}°C",
                           f"source: {data.get('temp_source', '?')}",
                           color=tc)

        fan_pct = int(data['fan'] / max(data['fan_max'], 1) * 100)
        fans = data.get('fans') or []
        if len(fans) >= 2:
            fan_sub = f"{fan_pct}%  ·  L {fans[0][0]:,} / R {fans[1][0]:,} RPM"
        else:
            fan_sub = f"{fan_pct}% of max {data['fan_max']:,}"
        self.c_fan.update(f"{data['fan']:>5,} RPM", fan_sub)

        vm = psutil.virtual_memory()
        used = (vm.total - vm.available) / 1024 ** 3
        total = vm.total / 1024 ** 3
        self.c_mem.update(f"{used:>4.1f} GB",
                          f"of {total:.1f} GB  ({data['mem']:>3.0f}%)")

        self.info_lbl.configure(
            text=f"Last updated: {data.get('timestamp', '—')}  ·  Interval: 1s"
        )

        # Only refresh the visible tab's extras
        self._tick += 1
        cur_tab = getattr(self, '_current_tab', None)
        if cur_tab is self._tab_fan:
            self._fc_update_loop()
        elif cur_tab is self._tab_graph and HAS_MPL:
            # matplotlib redraw is the heaviest thing here — every 2nd tick
            if self._tick % 2 == 0:
                self._update_graphs(hist)

        self.root.after(1000, self._update_loop)

    def _update_graphs(self, hist):
        if not hist['cpu']:
            return

        keys = ['cpu', 'temp', 'fan']
        fmts = {'cpu': '{:.0f}%', 'temp': '{:.1f}°C', 'fan': '{:,.0f} RPM'}
        for i, (line, (ax, fill_color), (_, ylim), key) in enumerate(
                zip(self._graph_lines, self._graph_fills,
                    self._graph_axes, keys)):
            data = hist[key]
            if not data:
                continue
            # Temperature line takes a semantic color (cool/warm/hot)
            color = temp_color(data[-1]) if key == 'temp' else fill_color
            x = list(range(len(data)))
            line.set_data(x, data)
            line.set_color(color)
            ax.set_xlim(0, max(len(data) - 1, 1))
            if ylim is None:
                mn, mx = min(data), max(data)
                pad = max((mx - mn) * 0.1, 2)
                ax.set_ylim(mn - pad, mx + pad)

            # Layered gradient fill — dense at the line, fading downward
            # (remove old collections, re-add: same cheap redraw approach)
            base = ax.get_ylim()[0]
            for coll in list(ax.collections):
                coll.remove()
            for f, a in ((0.78, 0.10), (0.55, 0.08),
                         (0.30, 0.06), (0.0, 0.05)):
                lower = [base + (v - base) * f for v in data]
                ax.fill_between(x, data, lower, color=color,
                                alpha=a, linewidth=0)

            # Latest-point marker + value badge
            mark, ann = self._graph_marks[i]
            mark.set_data([x[-1]], [data[-1]])
            mark.set_markeredgecolor(color)
            ann.xy = (x[-1], data[-1])
            ann.set_text(fmts[key].format(data[-1]))
            ann.set_visible(True)

        # Keep alert line in sync
        self._alert_line.set_ydata([self.monitor.temp_alert,
                                     self.monitor.temp_alert])
        self.mpl_canvas.draw_idle()

    # ── Run ───────────────────────────────────────────────────────────────────

    def run(self):
        self.root.protocol('WM_DELETE_WINDOW', self._on_close)
        self.root.mainloop()

    def _on_close(self):
        self._save_cfg()
        self.monitor.stop()
        try:
            self._menubar_proc.terminate()
        except Exception:
            pass
        self.root.destroy()


if __name__ == '__main__':
    DashboardApp().run()
