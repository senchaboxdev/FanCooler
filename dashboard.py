#!/usr/bin/env python3
import tkinter as tk
from tkinter import ttk, messagebox
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

# ── Color palette ─────────────────────────────────────────────────────────────
BG       = '#070a0e'
CARD     = '#10151d'
BORDER   = '#202938'
TEXT     = '#edf2f8'
DIM      = '#7e8b9d'
ACCENT   = '#4fd6e3'
GREEN    = '#43d97e'
YELLOW   = '#e3b341'
ORANGE   = '#ff9447'
RED      = '#ff5c5c'
BLUE     = '#6ab8ff'

def temp_color(t):
    if t < 55:  return GREEN
    if t < 70:  return YELLOW
    if t < 80:  return ORANGE
    return RED

def fan_color(pct):
    if pct < 40: return GREEN
    if pct < 70: return YELLOW
    return RED


def _shade(hex_color, factor):
    """Darken a #rrggbb color by factor (0..1) — used for glow halos."""
    r = int(hex_color[1:3], 16)
    g = int(hex_color[3:5], 16)
    b = int(hex_color[5:7], 16)
    return '#{:02x}{:02x}{:02x}'.format(
        int(r * factor), int(g * factor), int(b * factor))


# ── Gauge widget ──────────────────────────────────────────────────────────────
class CircleGauge(tk.Canvas):
    """Instrument-style gauge: tick bezel, glowing value arc, eased needle."""
    START  = 210   # degrees CCW from 3-o'clock = ~8 o'clock
    SWEEP  = -240  # clockwise 240°
    TICKS  = 25
    MAJOR  = 6     # every Nth tick is a major tick

    def __init__(self, parent, size=140, label='', unit='',
                 min_val=0, max_val=100, **kw):
        super().__init__(parent, width=size, height=size + 30,
                         bg=CARD, highlightthickness=0, **kw)
        self.size = size
        self.min_val = min_val
        self.max_val = max_val
        self._value = 0.0
        self._target = 0.0
        self._color = GREEN
        self._anim_running = False

        # All items created once; set_value() mutates them in place.
        s = size
        pad = self._pad = 20
        cx, cy = s // 2, s // 2

        # Tick bezel
        for i in range(self.TICKS):
            frac = i / float(self.TICKS - 1)
            a = math.radians(self.START + self.SWEEP * frac)
            major = (i % self.MAJOR == 0)
            r_out = s / 2 - 3
            r_in  = r_out - (7 if major else 4)
            self.create_line(cx + r_in * math.cos(a), cy - r_in * math.sin(a),
                             cx + r_out * math.cos(a), cy - r_out * math.sin(a),
                             fill='#2c3849' if major else '#1b232f',
                             width=2 if major else 1)

        # Track, glow underlay, value arc
        self.create_arc(pad, pad, s - pad, s - pad,
                        start=self.START, extent=self.SWEEP,
                        outline='#151b25', style='arc', width=9)
        self._glow_arc = self.create_arc(pad, pad, s - pad, s - pad,
                                         start=self.START, extent=0,
                                         outline=_shade(GREEN, 0.35),
                                         style='arc', width=13, state='hidden')
        self._val_arc = self.create_arc(pad, pad, s - pad, s - pad,
                                        start=self.START, extent=0,
                                        outline=self._color, style='arc',
                                        width=5, state='hidden')

        # Needle tip: halo + dot
        self._halo = self.create_oval(0, 0, 0, 0, outline='',
                                      fill=_shade(GREEN, 0.35))
        self._dot = self.create_oval(0, 0, 0, 0,
                                     fill=self._color, outline='')

        self._val_txt = self.create_text(cx, cy - 5, text='0', fill=TEXT,
                                         font=('DIN Alternate', 26, 'bold'))
        self.create_text(cx, cy + 17, text=unit.upper(), fill=DIM,
                         font=('Menlo', 8))
        self.create_text(cx, s + 14, text=' '.join(label.upper()),
                         fill=DIM, font=('Menlo', 8))
        self._render()

    def set_value(self, value, color=None):
        if color:
            self._color = color
        self._target = float(value)
        if not self._anim_running:
            self._anim_running = True
            self._animate()

    def _animate(self):
        """Glide toward the target value (ease-out) instead of jumping."""
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

    def _render(self):
        s, pad = self.size, self._pad
        cx, cy = s // 2, s // 2
        range_ = self.max_val - self.min_val or 1
        pct = max(0.0, min(1.0, (self._value - self.min_val) / range_))
        glow = _shade(self._color, 0.35)

        if pct > 0.005:
            ext = self.SWEEP * pct
            self.itemconfigure(self._glow_arc, extent=ext,
                               outline=glow, state='normal')
            self.itemconfigure(self._val_arc, extent=ext,
                               outline=self._color, state='normal')
        else:
            self.itemconfigure(self._glow_arc, state='hidden')
            self.itemconfigure(self._val_arc, state='hidden')

        a = math.radians(self.START + self.SWEEP * pct)
        r = s / 2 - pad
        nx = cx + r * math.cos(a)
        ny = cy - r * math.sin(a)
        self.coords(self._halo, nx - 7, ny - 7, nx + 7, ny + 7)
        self.coords(self._dot, nx - 3.5, ny - 3.5, nx + 3.5, ny + 3.5)
        self.itemconfigure(self._halo, fill=glow)
        self.itemconfigure(self._dot, fill=self._color)
        self.itemconfigure(self._val_txt, text='{:.0f}'.format(self._value))


# ── Stat card ─────────────────────────────────────────────────────────────────
class StatCard(tk.Frame):
    def __init__(self, parent, title, accent=ACCENT, **kw):
        outer = tk.Frame(parent, bg=BORDER, padx=1, pady=1)
        super().__init__(outer, bg=CARD, padx=14, pady=11, **kw)
        super().pack(fill='both', expand=True)
        self._outer = outer

        tk.Frame(self, bg=accent, height=2, width=28).pack(anchor='w')
        tk.Frame(self, bg=CARD, height=6).pack()
        tk.Label(self, text=title.upper(), bg=CARD, fg=DIM,
                 font=('Menlo', 8)).pack(anchor='w')
        self.val_var = tk.StringVar(value='—')
        self.val_lbl = tk.Label(self, textvariable=self.val_var,
                                bg=CARD, fg=TEXT,
                                font=('DIN Alternate', 21, 'bold'))
        self.val_lbl.pack(anchor='w')
        self.sub_var = tk.StringVar()
        tk.Label(self, textvariable=self.sub_var, bg=CARD, fg=DIM,
                 font=('Menlo', 8)).pack(anchor='w')

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
    def __init__(self):
        self.root = tk.Tk()
        self.root.title('FanCooler')
        self.root.geometry('820x600')
        self.root.configure(bg=BG)
        self.root.resizable(True, True)
        self.root.minsize(720, 520)

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
        # Header bar
        hdr = tk.Frame(self.root, bg='#04070b', height=56)
        hdr.pack(fill='x')
        hdr.pack_propagate(False)

        brand = tk.Frame(hdr, bg='#04070b')
        brand.pack(side='left', padx=20)
        brand_row = tk.Frame(brand, bg='#04070b')
        brand_row.pack(anchor='w', pady=(9, 0))
        tk.Label(brand_row, text='FAN', bg='#04070b', fg=TEXT,
                 font=('DIN Alternate', 20, 'bold')).pack(side='left')
        tk.Label(brand_row, text='COOLER', bg='#04070b', fg=ACCENT,
                 font=('DIN Alternate', 20, 'bold')).pack(side='left')
        tk.Label(brand, text='T H E R M A L   C O N T R O L',
                 bg='#04070b', fg=DIM, font=('Menlo', 7)).pack(anchor='w')

        status = tk.Frame(hdr, bg='#04070b')
        status.pack(side='right', padx=20)
        self._pulse_dot = tk.Canvas(status, width=10, height=10,
                                    bg='#04070b', highlightthickness=0)
        self._pulse_item = self._pulse_dot.create_oval(
            2, 2, 8, 8, fill=GREEN, outline='')
        self._pulse_dot.pack(side='left')
        self.status_lbl = tk.Label(status, text=' MONITORING',
                                   bg='#04070b', fg=GREEN,
                                   font=('Menlo', 9))
        self.status_lbl.pack(side='left')
        self._pulse_on = True
        self._pulse()

        tk.Frame(self.root, bg='#0c3340', height=2).pack(fill='x')

        # Notebook
        style = ttk.Style()
        style.theme_use('default')
        style.configure('FC.TNotebook', background=BG, borderwidth=0, tabmargins=0)
        style.configure('FC.TNotebook.Tab', background='#10151d', foreground=DIM,
                        padding=[20, 9], font=('Menlo', 10))
        style.map('FC.TNotebook.Tab',
                  background=[('selected', CARD)],
                  foreground=[('selected', TEXT)])

        self.nb = ttk.Notebook(self.root, style='FC.TNotebook')
        self.nb.pack(fill='both', expand=True)

        self._build_dashboard_tab()
        self._build_graph_tab()
        self._build_fanctrl_tab()
        self._build_settings_tab()

    def _pulse(self):
        """Blink the header status dot — instrument 'alive' indicator."""
        try:
            self._pulse_on = not self._pulse_on
            self._pulse_dot.itemconfigure(
                self._pulse_item,
                fill=GREEN if self._pulse_on else '#16482b')
            self.root.after(700, self._pulse)
        except tk.TclError:
            pass

    def _build_dashboard_tab(self):
        tab = tk.Frame(self.nb, bg=BG)
        self._tab_dash = tab
        self.nb.add(tab, text='  DASHBOARD  ')

        # Gauges
        gauge_row = tk.Frame(tab, bg=BG)
        gauge_row.pack(fill='x', padx=24, pady=(18, 10))

        self.g_cpu  = CircleGauge(gauge_row, label='CPU Usage',   unit='%',   min_val=0, max_val=100)
        self.g_temp = CircleGauge(gauge_row, label='Temperature', unit='°C',  min_val=0, max_val=100)
        self.g_fan  = CircleGauge(gauge_row, label='Fan Speed',   unit='RPM', min_val=0, max_val=6000)
        self.g_mem  = CircleGauge(gauge_row, label='Memory',      unit='%',   min_val=0, max_val=100)

        for g in (self.g_cpu, self.g_temp, self.g_fan, self.g_mem):
            g.pack(side='left', padx=(0, 18))

        tk.Frame(tab, bg=BORDER, height=1).pack(fill='x', padx=24, pady=6)

        # Stat cards
        cards = tk.Frame(tab, bg=BG)
        cards.pack(fill='x', padx=24, pady=6)
        cards.columnconfigure((0, 1, 2, 3), weight=1, uniform='c')

        self.c_freq = StatCard(cards, 'CPU Frequency', accent=ACCENT)
        self.c_freq.grid_outer(row=0, column=0, sticky='nsew', padx=(0, 8))

        self.c_temp = StatCard(cards, 'Temperature', accent=ORANGE)
        self.c_temp.grid_outer(row=0, column=1, sticky='nsew', padx=(0, 8))

        self.c_fan = StatCard(cards, 'Fan Speed', accent=BLUE)
        self.c_fan.grid_outer(row=0, column=2, sticky='nsew', padx=(0, 8))

        self.c_mem = StatCard(cards, 'Memory Used', accent=GREEN)
        self.c_mem.grid_outer(row=0, column=3, sticky='nsew')

        # Footer info bar
        foot = tk.Frame(tab, bg=CARD)
        foot.pack(fill='x', side='bottom')
        tk.Frame(foot, bg=BORDER, height=1).pack(fill='x')
        self.info_lbl = tk.Label(foot, text='', bg=CARD, fg=DIM,
                                 font=('Helvetica Neue', 11), anchor='w',
                                 padx=16, pady=6)
        self.info_lbl.pack(fill='x')

    def _build_graph_tab(self):
        tab = tk.Frame(self.nb, bg=BG)
        self._tab_graph = tab
        self.nb.add(tab, text='  HISTORY  ')

        if not HAS_MPL:
            tk.Label(tab,
                     text='matplotlib not installed.\n\nRun:  pip install matplotlib',
                     bg=BG, fg=DIM, font=('Helvetica Neue', 13)).pack(expand=True)
            return

        matplotlib.rcParams.update({
            'axes.facecolor':   CARD,
            'figure.facecolor': BG,
            'axes.edgecolor':   BORDER,
            'axes.labelcolor':  DIM,
            'xtick.color':      DIM,
            'ytick.color':      DIM,
            'grid.color':       BORDER,
            'text.color':       TEXT,
        })

        self.fig = Figure(figsize=(8, 4.8), dpi=96, facecolor=BG)
        self.fig.subplots_adjust(hspace=0.42, left=0.08,
                                 right=0.97, top=0.94, bottom=0.06)

        self.ax_cpu  = self.fig.add_subplot(3, 1, 1)
        self.ax_temp = self.fig.add_subplot(3, 1, 2)
        self.ax_fan  = self.fig.add_subplot(3, 1, 3)

        fan_top = 6500
        fans = self.monitor.fan_ctrl.get_fan_info()
        if fans:
            fan_top = max(f[2] for f in fans) + 300

        graph_specs = [
            (self.ax_cpu,  'CPU %',   (0, 100), ACCENT),
            (self.ax_temp, 'Temp °C', None,     ORANGE),
            (self.ax_fan,  'Fan RPM', (0, fan_top), BLUE),
        ]
        self._graph_lines = []
        self._graph_fills = []
        self._graph_axes  = []
        for ax, label, ylim, color in graph_specs:
            ax.set_facecolor(CARD)
            ax.grid(True, alpha=0.3, color=BORDER)
            for sp in ax.spines.values():
                sp.set_color(BORDER)
            ax.tick_params(colors=DIM, labelsize=8)
            ax.set_ylabel(label, fontsize=9, color=DIM)
            if ylim:
                ax.set_ylim(*ylim)
            line, = ax.plot([], [], color=color, linewidth=2,
                            solid_capstyle='round', animated=False)
            fill = ax.fill_between([], [], alpha=0.18, color=color)
            self._graph_lines.append(line)
            self._graph_fills.append((ax, color))
            self._graph_axes.append((ax, ylim))

        # Alert line on temp graph (static)
        self._alert_line = self.ax_temp.axhline(
            y=80, color=RED, linestyle='--', alpha=0.5, linewidth=1.2)

        self.mpl_canvas = FigureCanvasTkAgg(self.fig, master=tab)
        self.mpl_canvas.draw()
        self.mpl_canvas.get_tk_widget().pack(fill='both', expand=True, padx=4, pady=4)

    def _build_fanctrl_tab(self):
        fc = self.monitor.fan_ctrl          # shorthand
        tab = tk.Frame(self.nb, bg=BG)
        self._tab_fan = tab
        self.nb.add(tab, text='  FAN CONTROL  ')

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

        pad = dict(padx=36, pady=0, anchor='w')

        # ── Status card ────────────────────────────────────────────
        tk.Frame(inner, bg=BG, height=20).pack()
        status_outer = tk.Frame(inner, bg=BORDER, padx=1, pady=1)
        status_outer.pack(fill='x', padx=36, pady=(0, 16))
        status_card = tk.Frame(status_outer, bg=CARD, padx=16, pady=14)
        status_card.pack(fill='both', expand=True)

        row1 = tk.Frame(status_card, bg=CARD)
        row1.pack(fill='x')
        tk.Label(row1, text='Tool:', bg=CARD, fg=DIM,
                 font=('Helvetica Neue', 12)).pack(side='left')
        if fc.available:
            tool_txt = 'smc_tool ready ({} fans)'.format(fc.num_fans)
            tool_clr = GREEN
        else:
            tool_txt = 'smc_tool not found'
            tool_clr = RED
        self.fc_tool_lbl = tk.Label(row1, text=tool_txt, bg=CARD, fg=tool_clr,
                                    font=('Menlo', 11, 'bold'))
        self.fc_tool_lbl.pack(side='left', padx=8)

        self.fc_mode_lbl = tk.Label(status_card, text='Mode: Auto',
                                    bg=CARD, fg=DIM,
                                    font=('Helvetica Neue', 11))
        self.fc_mode_lbl.pack(anchor='w', pady=(4, 0))

        self.fc_status_lbl = tk.Label(status_card, text='',
                                      bg=CARD, fg=ACCENT,
                                      font=('Helvetica Neue', 11))
        self.fc_status_lbl.pack(anchor='w')

        # ── One-time sudo setup row ────────────────────────────────
        tk.Frame(status_card, bg=BORDER, height=1).pack(fill='x', pady=(10, 6))
        setup_row = tk.Frame(status_card, bg=CARD)
        setup_row.pack(fill='x')
        tk.Label(setup_row, text='Sudo access:', bg=CARD, fg=DIM,
                 font=('Helvetica Neue', 12)).pack(side='left')

        if fc.is_setup:
            self.fc_sudo_lbl = tk.Label(setup_row,
                                        text='No password needed',
                                        bg=CARD, fg=GREEN,
                                        font=('Menlo', 11, 'bold'))
            self.fc_sudo_lbl.pack(side='left', padx=8)
            self.fc_setup_btn = None
        else:
            self.fc_sudo_lbl = tk.Label(setup_row,
                                        text='Password required each time',
                                        bg=CARD, fg=YELLOW,
                                        font=('Helvetica Neue', 12))
            self.fc_sudo_lbl.pack(side='left', padx=8)
            self.fc_setup_btn = tk.Button(
                setup_row,
                text='One-time Setup',
                bg='#0c3340', fg=ACCENT, relief='flat',
                padx=12, pady=4,
                font=('Menlo', 10, 'bold'),
                highlightbackground=ACCENT, highlightthickness=1,
                activebackground=ACCENT, activeforeground=BG,
                cursor='hand2',
                command=self._fc_do_setup)
            self.fc_setup_btn.pack(side='left')
            tk.Label(setup_row,
                     text='  (asks once, then never again)',
                     bg=CARD, fg=DIM,
                     font=('Menlo', 9)).pack(side='left')

        # ── Auto-boost section ─────────────────────────────────────
        tk.Label(inner, text='Auto-Boost', bg=BG, fg=TEXT,
                 font=('DIN Alternate', 15, 'bold')).pack(**pad)
        tk.Label(inner,
                 text='Automatically raise fan speed when temperature is high.',
                 bg=BG, fg=DIM, font=('Helvetica Neue', 11)).pack(**pad)
        tk.Frame(inner, bg=BG, height=8).pack()

        self.fc_auto_var = tk.BooleanVar(
            value=self._cfg.get('auto_boost', False))
        tk.Checkbutton(inner, text='Enable auto-boost',
                       variable=self.fc_auto_var, bg=BG, fg=TEXT,
                       selectcolor=CARD, activebackground=BG,
                       font=('Helvetica Neue', 13),
                       command=self._fc_apply_auto).pack(**pad)

        boost_row = tk.Frame(inner, bg=BG)
        boost_row.pack(anchor='w', padx=36, pady=6)
        tk.Label(boost_row, text='Boost when temp >', bg=BG, fg=DIM,
                 font=('Helvetica Neue', 12)).pack(side='left')
        self.fc_thresh_var = tk.DoubleVar(
            value=self._cfg.get('boost_thresh', 75.0))
        tk.Scale(boost_row, from_=55, to=90, variable=self.fc_thresh_var,
                 orient='horizontal', length=160, bg=CARD, fg=TEXT,
                 troughcolor='#19202b', highlightthickness=0,
                 activebackground=ORANGE,
                 command=self._fc_apply_auto).pack(side='left', padx=6)
        self.fc_thresh_lbl = tk.Label(boost_row, text='75C', bg=BG, fg=ORANGE,
                                      font=('Menlo', 11, 'bold'))
        self.fc_thresh_lbl.pack(side='left')

        rpm_row = tk.Frame(inner, bg=BG)
        rpm_row.pack(anchor='w', padx=36, pady=6)
        tk.Label(rpm_row, text='Boost to RPM:', bg=BG, fg=DIM,
                 font=('Helvetica Neue', 12)).pack(side='left')
        self.fc_boost_rpm_var = tk.IntVar(
            value=self._cfg.get('boost_rpm', 4000))
        tk.Scale(rpm_row, from_=1200, to=6200, variable=self.fc_boost_rpm_var,
                 orient='horizontal', length=160, bg=CARD, fg=TEXT,
                 troughcolor='#19202b', highlightthickness=0,
                 activebackground=BLUE, resolution=100,
                 command=self._fc_apply_auto).pack(side='left', padx=6)
        self.fc_boost_rpm_lbl = tk.Label(rpm_row, text='4000 RPM', bg=BG, fg=BLUE,
                                         font=('Menlo', 11, 'bold'))
        self.fc_boost_rpm_lbl.pack(side='left')

        tk.Frame(inner, bg=BORDER, height=1, width=500).pack(anchor='w', padx=36, pady=14)

        # ── Manual control section ─────────────────────────────────
        tk.Label(inner, text='Manual Fan Speed', bg=BG, fg=TEXT,
                 font=('DIN Alternate', 15, 'bold')).pack(**pad)
        tk.Label(inner,
                 text='Set minimum fan RPM directly. "Auto" hands control back to macOS.',
                 bg=BG, fg=DIM, font=('Helvetica Neue', 11)).pack(**pad)
        tk.Frame(inner, bg=BG, height=10).pack()

        # Preset buttons — bright colors so they're clearly clickable
        preset_row = tk.Frame(inner, bg=BG)
        preset_row.pack(anchor='w', padx=36, pady=4)
        self._preset_btns = {}
        preset_colors = {
            'Auto':        ('#202938', TEXT),
            'Eco':         ('#0f3322', GREEN),
            'Normal':      ('#0c3340', ACCENT),
            'Performance': ('#3a2a0c', YELLOW),
            'Max':         ('#3a1414', RED),
        }
        for name, rpm in [('Auto', 0), ('Eco', 1200),
                          ('Normal', 2500), ('Performance', 4000), ('Max', 6200)]:
            bg_c, fg_c = preset_colors.get(name, (CARD, TEXT))
            sub = 'auto' if rpm == 0 else '{} RPM'.format(rpm)
            btn = tk.Button(
                preset_row,
                text='{}\n{}'.format(name, sub),
                bg=bg_c, fg=fg_c, relief='flat', padx=14, pady=10,
                font=('Menlo', 10, 'bold'),
                highlightbackground=fg_c, highlightthickness=1,
                activebackground=fg_c, activeforeground=BG,
                cursor='hand2',
                command=lambda n=name: self._fc_preset(n))
            btn.pack(side='left', padx=(0, 8))
            self._preset_btns[name] = btn

        # Manual slider
        man_row = tk.Frame(inner, bg=BG)
        man_row.pack(anchor='w', padx=36, pady=10)
        tk.Label(man_row, text='Custom RPM:', bg=BG, fg=DIM,
                 font=('Helvetica Neue', 12)).pack(side='left')
        self.fc_man_rpm_var = tk.IntVar(
            value=self._cfg.get('manual_rpm', 2500))
        tk.Scale(man_row, from_=0, to=6200, variable=self.fc_man_rpm_var,
                 orient='horizontal', length=220, bg=CARD, fg=TEXT,
                 troughcolor='#19202b', highlightthickness=0,
                 activebackground=ACCENT, resolution=100).pack(side='left', padx=6)
        self.fc_man_rpm_lbl = tk.Label(
            man_row, text='{} RPM'.format(self.fc_man_rpm_var.get()),
            bg=BG, fg=ACCENT, font=('Menlo', 11, 'bold'))
        self.fc_man_rpm_lbl.pack(side='left')
        self.fc_man_rpm_var.trace('w', self._fc_update_man_lbl)

        # Apply / Reset buttons
        btn_row = tk.Frame(inner, bg=BG)
        btn_row.pack(anchor='w', padx=36, pady=8)
        self.fc_apply_btn = tk.Button(
            btn_row, text='Apply', bg=ACCENT, fg=BG, relief='flat',
            padx=20, pady=7, font=('Menlo', 11, 'bold'),
            activebackground='#6ab8ff', activeforeground=BG, cursor='hand2',
            command=self._fc_apply_manual)
        self.fc_apply_btn.pack(side='left', padx=(0, 10))
        self.fc_reset_btn = tk.Button(
            btn_row, text='Reset to Auto', bg='#0f3322', fg=GREEN, relief='flat',
            padx=20, pady=7, font=('Menlo', 11, 'bold'),
            highlightbackground=GREEN, highlightthickness=1, cursor='hand2',
            command=self._fc_reset)
        self.fc_reset_btn.pack(side='left')

        # ── Status note when tool missing ──────────────────────────
        tk.Frame(inner, bg=BORDER, height=1, width=500).pack(anchor='w', padx=36, pady=14)
        if not fc.available:
            note = tk.Frame(inner, bg=BG)
            note.pack(anchor='w', padx=36, pady=4)
            tk.Label(note,
                     text='smc_tool not found in app directory.',
                     bg=BG, fg=RED, font=('Menlo', 11, 'bold')).pack(anchor='w')
            tk.Label(note,
                     text='Re-clone the repo or copy smc_tool next to dashboard.py.',
                     bg=BG, fg=DIM, font=('Helvetica Neue', 11)).pack(anchor='w', pady=2)

        tk.Frame(inner, bg=BG, height=24).pack()   # bottom padding

        # Push loaded config into the controller and sync labels
        self._fc_apply_auto()

        # Disable controls if tool not available
        if not fc.available:
            self._fc_set_controls_state('disabled')

    def _build_settings_tab(self):
        tab = tk.Frame(self.nb, bg=BG)
        self.nb.add(tab, text='  SETTINGS  ')

        inner = tk.Frame(tab, bg=BG)
        inner.pack(padx=40, pady=28, anchor='nw')

        # Alert section
        tk.Label(inner, text='Temperature Alerts', bg=BG, fg=TEXT,
                 font=('DIN Alternate', 16, 'bold')).pack(anchor='w', pady=(0, 14))

        tk.Checkbutton(inner, text='Enable alerts when temperature exceeds threshold',
                       variable=self.alert_enabled, bg=BG, fg=TEXT,
                       selectcolor=CARD, activebackground=BG, activeforeground=TEXT,
                       font=('Helvetica Neue', 13),
                       command=self._apply_alert_settings).pack(anchor='w', pady=2)

        row = tk.Frame(inner, bg=BG)
        row.pack(anchor='w', pady=10)
        tk.Label(row, text='Alert at:', bg=BG, fg=DIM,
                 font=('Helvetica Neue', 13)).pack(side='left', padx=(0, 10))
        self.alert_scale = tk.Scale(
            row, from_=50, to=100, variable=self.temp_alert_var,
            orient='horizontal', length=220, bg=CARD, fg=TEXT,
            troughcolor='#19202b', highlightthickness=0,
            activebackground=ACCENT, command=self._apply_alert_settings)
        self.alert_scale.pack(side='left')
        self.alert_val_lbl = tk.Label(row, text='80°C', bg=BG, fg=ORANGE,
                                      font=('Menlo', 12, 'bold'))
        self.alert_val_lbl.pack(side='left', padx=10)

        tk.Frame(inner, bg=BORDER, height=1, width=440).pack(anchor='w', pady=18)

        # System info section
        tk.Label(inner, text='System Info', bg=BG, fg=TEXT,
                 font=('DIN Alternate', 16, 'bold')).pack(anchor='w', pady=(0, 12))
        self.sys_info_lbl = tk.Label(inner, text='', bg=BG, fg=DIM,
                                     font=('Helvetica Neue', 12), justify='left')
        self.sys_info_lbl.pack(anchor='w')
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
            text='{:.0f}C'.format(fc.boost_thresh))
        self.fc_boost_rpm_lbl.configure(
            text='{} RPM'.format(fc.boost_rpm))
        self._save_cfg()

    def _fc_update_man_lbl(self, *_):
        self.fc_man_rpm_lbl.configure(
            text='{} RPM'.format(self.fc_man_rpm_var.get()))

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
                        text='No password needed', fg=GREEN)
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
        """Update fan control status label from monitor loop."""
        fc = self.monitor.fan_ctrl
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
        self.alert_val_lbl.configure(text=f'{val:.0f}°C')
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

        self.c_freq.update(f"{data['cpu_freq']:.0f} MHz",
                           f"CPU load: {data['cpu']:.1f}%")
        self.c_temp.update(f"{data['temp']:.1f}°C",
                           f"source: {data.get('temp_source', '?')}",
                           color=tc)

        fan_pct = int(data['fan'] / max(data['fan_max'], 1) * 100)
        fans = data.get('fans') or []
        if len(fans) >= 2:
            fan_sub = f"{fan_pct}%  ·  L {fans[0][0]:,} / R {fans[1][0]:,} RPM"
        else:
            fan_sub = f"{fan_pct}% of max {data['fan_max']:,}"
        self.c_fan.update(f"{data['fan']:,} RPM", fan_sub)

        vm = psutil.virtual_memory()
        used = (vm.total - vm.available) / 1024 ** 3
        total = vm.total / 1024 ** 3
        self.c_mem.update(f"{used:.1f} GB",
                          f"of {total:.1f} GB  ({data['mem']:.0f}%)")

        self.info_lbl.configure(
            text=f"Last updated: {data.get('timestamp', '—')}  ·  Interval: 1s"
        )

        # Only refresh the visible tab's extras
        self._tick += 1
        try:
            cur_tab = self.nb.nametowidget(self.nb.select())
        except Exception:
            cur_tab = None
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
        for i, (line, (ax, fill_color), (_, ylim), key) in enumerate(
                zip(self._graph_lines, self._graph_fills,
                    self._graph_axes, keys)):
            data = hist[key]
            if not data:
                continue
            x = list(range(len(data)))
            line.set_data(x, data)
            ax.set_xlim(0, max(len(data) - 1, 1))
            if ylim is None:
                mn, mx = min(data), max(data)
                pad = max((mx - mn) * 0.1, 2)
                ax.set_ylim(mn - pad, mx + pad)

            # Redraw fill (cheap: remove old, add new)
            for coll in list(ax.collections):
                coll.remove()
            ax.fill_between(x, data, alpha=0.18, color=fill_color)

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
