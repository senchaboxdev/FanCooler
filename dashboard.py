#!/usr/bin/env python3
import tkinter as tk
from tkinter import ttk, messagebox
import psutil
import subprocess
import platform
import math
import sys
import os

try:
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    import matplotlib
    HAS_MPL = True
except ImportError:
    HAS_MPL = False

from monitor import SystemMonitor

# ── Color palette ─────────────────────────────────────────────────────────────
BG       = '#0d1117'
CARD     = '#161b22'
BORDER   = '#30363d'
TEXT     = '#e6edf3'
DIM      = '#8b949e'
ACCENT   = '#58a6ff'
GREEN    = '#3fb950'
YELLOW   = '#d29922'
ORANGE   = '#db6d28'
RED      = '#f85149'
BLUE     = '#79c0ff'

def temp_color(t):
    if t < 55:  return GREEN
    if t < 70:  return YELLOW
    if t < 80:  return ORANGE
    return RED

def fan_color(pct):
    if pct < 40: return GREEN
    if pct < 70: return YELLOW
    return RED


# ── Gauge widget ──────────────────────────────────────────────────────────────
class CircleGauge(tk.Canvas):
    START  = 210   # degrees CCW from 3-o'clock = ~8 o'clock
    SWEEP  = -240  # clockwise 240°

    def __init__(self, parent, size=128, label='', unit='',
                 min_val=0, max_val=100, **kw):
        super().__init__(parent, width=size, height=size + 26,
                         bg=CARD, highlightthickness=0, **kw)
        self.size = size
        self.label = label
        self.unit = unit
        self.min_val = min_val
        self.max_val = max_val
        self._value = 0
        self._color = GREEN
        self._draw()

    def set_value(self, value, color=None):
        self._value = value
        if color:
            self._color = color
        self._draw()

    def _draw(self):
        self.delete('all')
        s = self.size
        pad = 14
        cx, cy = s // 2, s // 2

        # Background arc
        self.create_arc(pad, pad, s - pad, s - pad,
                        start=self.START, extent=self.SWEEP,
                        outline='#21262d', style='arc', width=10)

        # Value arc
        range_ = self.max_val - self.min_val or 1
        pct = max(0.0, min(1.0, (self._value - self.min_val) / range_))
        if pct > 0.005:
            self.create_arc(pad, pad, s - pad, s - pad,
                            start=self.START, extent=self.SWEEP * pct,
                            outline=self._color, style='arc', width=10)

        # Needle tip dot
        angle_deg = self.START + self.SWEEP * pct
        angle_rad = math.radians(angle_deg)
        r = s // 2 - pad
        nx = cx + r * math.cos(angle_rad)
        ny = cy - r * math.sin(angle_rad)
        self.create_oval(nx - 4, ny - 4, nx + 4, ny + 4,
                         fill=self._color, outline='')

        # Value text
        val_str = f'{self._value:.0f}'
        self.create_text(cx, cy - 6, text=val_str, fill=TEXT,
                         font=('SF Pro Display', 20, 'bold'))
        self.create_text(cx, cy + 14, text=self.unit, fill=DIM,
                         font=('SF Pro Display', 10))

        # Label
        self.create_text(cx, s + 13, text=self.label, fill=DIM,
                         font=('SF Pro Display', 10))


# ── Stat card ─────────────────────────────────────────────────────────────────
class StatCard(tk.Frame):
    def __init__(self, parent, title, **kw):
        outer = tk.Frame(parent, bg=BORDER, padx=1, pady=1)
        super().__init__(outer, bg=CARD, padx=12, pady=10, **kw)
        super().pack(fill='both', expand=True)
        self._outer = outer

        tk.Label(self, text=title, bg=CARD, fg=DIM,
                 font=('SF Pro Display', 9)).pack(anchor='w')
        self.val_var = tk.StringVar(value='—')
        self.val_lbl = tk.Label(self, textvariable=self.val_var,
                                bg=CARD, fg=TEXT,
                                font=('SF Pro Display', 17, 'bold'))
        self.val_lbl.pack(anchor='w')
        self.sub_var = tk.StringVar()
        tk.Label(self, textvariable=self.sub_var, bg=CARD, fg=DIM,
                 font=('SF Pro Display', 9)).pack(anchor='w')

    def grid_outer(self, **kw):
        self._outer.grid(**kw)

    def pack_outer(self, **kw):
        self._outer.pack(**kw)

    def update(self, value, sub='', color=TEXT):
        self.val_var.set(value)
        self.sub_var.set(sub)
        self.val_lbl.configure(fg=color)


# ── Main application ──────────────────────────────────────────────────────────
def _setup_dock_icon():
    """Show exactly one Dock icon with the FanCooler icon (not Python's default)."""
    try:
        from AppKit import NSApplication, NSImage
        app = NSApplication.sharedApplication()
        # NSApplicationActivationPolicyRegular = 0  (normal app, shows in Dock)
        app.setActivationPolicy_(0)
        icns = os.path.expanduser(
            '~/Desktop/FanCooler.app/Contents/Resources/AppIcon.icns')
        icon = NSImage.alloc().initByReferencingFile_(icns)
        if icon:
            app.setApplicationIconImage_(icon)
    except Exception:
        pass


class DashboardApp:
    def __init__(self):
        _setup_dock_icon()
        self.root = tk.Tk()
        self.root.title('FanCooler')
        self.root.geometry('820x600')
        self.root.configure(bg=BG)
        self.root.resizable(True, True)
        self.root.minsize(720, 520)

        self.monitor = SystemMonitor()
        self.temp_alert_var = tk.DoubleVar(value=80.0)
        self.alert_enabled = tk.BooleanVar(value=True)
        self.monitor.on_high_temp = self._on_high_temp
        self.monitor.temp_alert = 80.0

        self._build_ui()
        self.monitor.start()
        self._start_menubar()
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
        hdr = tk.Frame(self.root, bg='#010409', height=48)
        hdr.pack(fill='x')
        hdr.pack_propagate(False)
        tk.Label(hdr, text='FanCooler', bg='#010409', fg=TEXT,
                 font=('SF Pro Display', 14, 'bold')).pack(side='left', padx=20, pady=12)
        self.status_lbl = tk.Label(hdr, text='* Monitoring', bg='#010409', fg=GREEN,
                                   font=('SF Pro Display', 10))
        self.status_lbl.pack(side='right', padx=20)

        tk.Frame(self.root, bg=BORDER, height=1).pack(fill='x')

        # Notebook
        style = ttk.Style()
        style.theme_use('default')
        style.configure('FC.TNotebook', background=BG, borderwidth=0, tabmargins=0)
        style.configure('FC.TNotebook.Tab', background='#161b22', foreground=DIM,
                        padding=[18, 8], font=('SF Pro Display', 11))
        style.map('FC.TNotebook.Tab',
                  background=[('selected', CARD)],
                  foreground=[('selected', TEXT)])

        self.nb = ttk.Notebook(self.root, style='FC.TNotebook')
        self.nb.pack(fill='both', expand=True)

        self._build_dashboard_tab()
        self._build_graph_tab()
        self._build_fanctrl_tab()
        self._build_settings_tab()

    def _build_dashboard_tab(self):
        tab = tk.Frame(self.nb, bg=BG)
        self.nb.add(tab, text='  Dashboard  ')

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

        self.c_freq = StatCard(cards, 'CPU FREQUENCY')
        self.c_freq.grid_outer(row=0, column=0, sticky='nsew', padx=(0, 8))

        self.c_temp = StatCard(cards, 'TEMPERATURE')
        self.c_temp.grid_outer(row=0, column=1, sticky='nsew', padx=(0, 8))

        self.c_fan = StatCard(cards, 'FAN SPEED')
        self.c_fan.grid_outer(row=0, column=2, sticky='nsew', padx=(0, 8))

        self.c_mem = StatCard(cards, 'MEMORY USED')
        self.c_mem.grid_outer(row=0, column=3, sticky='nsew')

        # Footer info bar
        foot = tk.Frame(tab, bg=CARD)
        foot.pack(fill='x', side='bottom')
        tk.Frame(foot, bg=BORDER, height=1).pack(fill='x')
        self.info_lbl = tk.Label(foot, text='', bg=CARD, fg=DIM,
                                 font=('SF Pro Display', 10), anchor='w',
                                 padx=16, pady=6)
        self.info_lbl.pack(fill='x')

    def _build_graph_tab(self):
        tab = tk.Frame(self.nb, bg=BG)
        self.nb.add(tab, text='  History  ')

        if not HAS_MPL:
            tk.Label(tab,
                     text='matplotlib not installed.\n\nRun:  pip install matplotlib',
                     bg=BG, fg=DIM, font=('SF Pro Display', 13)).pack(expand=True)
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

        graph_specs = [
            (self.ax_cpu,  'CPU %',   (0, 100), ACCENT),
            (self.ax_temp, 'Temp °C', None,     ORANGE),
            (self.ax_fan,  'Fan RPM', (0, 6200), BLUE),
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
            fill = ax.fill_between([], [], alpha=0.12, color=color)
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
        self.nb.add(tab, text='  Fan Control  ')

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
                 font=('SF Pro Display', 11)).pack(side='left')
        if fc.available:
            tool_txt = 'smcFanControl ready'
            tool_clr = GREEN
        else:
            tool_txt = 'smcFanControl not installed'
            tool_clr = RED
        self.fc_tool_lbl = tk.Label(row1, text=tool_txt, bg=CARD, fg=tool_clr,
                                    font=('SF Pro Display', 11, 'bold'))
        self.fc_tool_lbl.pack(side='left', padx=8)

        self.fc_mode_lbl = tk.Label(status_card, text='Mode: Auto',
                                    bg=CARD, fg=DIM,
                                    font=('SF Pro Display', 10))
        self.fc_mode_lbl.pack(anchor='w', pady=(4, 0))

        self.fc_status_lbl = tk.Label(status_card, text='',
                                      bg=CARD, fg=ACCENT,
                                      font=('SF Pro Display', 10))
        self.fc_status_lbl.pack(anchor='w')

        # ── One-time sudo setup row ────────────────────────────────
        tk.Frame(status_card, bg=BORDER, height=1).pack(fill='x', pady=(10, 6))
        setup_row = tk.Frame(status_card, bg=CARD)
        setup_row.pack(fill='x')
        tk.Label(setup_row, text='Sudo access:', bg=CARD, fg=DIM,
                 font=('SF Pro Display', 11)).pack(side='left')

        if fc.is_setup:
            self.fc_sudo_lbl = tk.Label(setup_row,
                                        text='No password needed',
                                        bg=CARD, fg=GREEN,
                                        font=('SF Pro Display', 11, 'bold'))
            self.fc_sudo_lbl.pack(side='left', padx=8)
            self.fc_setup_btn = None
        else:
            self.fc_sudo_lbl = tk.Label(setup_row,
                                        text='Password required each time',
                                        bg=CARD, fg=YELLOW,
                                        font=('SF Pro Display', 11))
            self.fc_sudo_lbl.pack(side='left', padx=8)
            self.fc_setup_btn = tk.Button(
                setup_row,
                text='One-time Setup',
                bg='#1a3a5c', fg=ACCENT, relief='flat',
                padx=12, pady=4,
                font=('SF Pro Display', 10, 'bold'),
                highlightbackground=ACCENT, highlightthickness=1,
                activebackground=ACCENT, activeforeground=BG,
                cursor='hand2',
                command=self._fc_do_setup)
            self.fc_setup_btn.pack(side='left')
            tk.Label(setup_row,
                     text='  (asks once, then never again)',
                     bg=CARD, fg=DIM,
                     font=('SF Pro Display', 9)).pack(side='left')

        # ── Auto-boost section ─────────────────────────────────────
        tk.Label(inner, text='Auto-Boost', bg=BG, fg=TEXT,
                 font=('SF Pro Display', 13, 'bold')).pack(**pad)
        tk.Label(inner,
                 text='Automatically raise fan speed when temperature is high.',
                 bg=BG, fg=DIM, font=('SF Pro Display', 10)).pack(**pad)
        tk.Frame(inner, bg=BG, height=8).pack()

        self.fc_auto_var = tk.BooleanVar(value=False)
        tk.Checkbutton(inner, text='Enable auto-boost',
                       variable=self.fc_auto_var, bg=BG, fg=TEXT,
                       selectcolor=CARD, activebackground=BG,
                       font=('SF Pro Display', 12),
                       command=self._fc_apply_auto).pack(**pad)

        boost_row = tk.Frame(inner, bg=BG)
        boost_row.pack(anchor='w', padx=36, pady=6)
        tk.Label(boost_row, text='Boost when temp >', bg=BG, fg=DIM,
                 font=('SF Pro Display', 11)).pack(side='left')
        self.fc_thresh_var = tk.DoubleVar(value=75.0)
        tk.Scale(boost_row, from_=55, to=90, variable=self.fc_thresh_var,
                 orient='horizontal', length=160, bg=CARD, fg=TEXT,
                 troughcolor='#21262d', highlightthickness=0,
                 activebackground=ORANGE,
                 command=self._fc_apply_auto).pack(side='left', padx=6)
        self.fc_thresh_lbl = tk.Label(boost_row, text='75C', bg=BG, fg=ORANGE,
                                      font=('SF Pro Display', 11, 'bold'))
        self.fc_thresh_lbl.pack(side='left')

        rpm_row = tk.Frame(inner, bg=BG)
        rpm_row.pack(anchor='w', padx=36, pady=6)
        tk.Label(rpm_row, text='Boost to RPM:', bg=BG, fg=DIM,
                 font=('SF Pro Display', 11)).pack(side='left')
        self.fc_boost_rpm_var = tk.IntVar(value=4000)
        tk.Scale(rpm_row, from_=1200, to=6200, variable=self.fc_boost_rpm_var,
                 orient='horizontal', length=160, bg=CARD, fg=TEXT,
                 troughcolor='#21262d', highlightthickness=0,
                 activebackground=BLUE, resolution=100,
                 command=self._fc_apply_auto).pack(side='left', padx=6)
        self.fc_boost_rpm_lbl = tk.Label(rpm_row, text='4000 RPM', bg=BG, fg=BLUE,
                                         font=('SF Pro Display', 11, 'bold'))
        self.fc_boost_rpm_lbl.pack(side='left')

        tk.Frame(inner, bg=BORDER, height=1, width=500).pack(anchor='w', padx=36, pady=14)

        # ── Manual control section ─────────────────────────────────
        tk.Label(inner, text='Manual Fan Speed', bg=BG, fg=TEXT,
                 font=('SF Pro Display', 13, 'bold')).pack(**pad)
        tk.Label(inner,
                 text='Set minimum fan RPM directly. "Auto" hands control back to macOS.',
                 bg=BG, fg=DIM, font=('SF Pro Display', 10)).pack(**pad)
        tk.Frame(inner, bg=BG, height=10).pack()

        # Preset buttons — bright colors so they're clearly clickable
        preset_row = tk.Frame(inner, bg=BG)
        preset_row.pack(anchor='w', padx=36, pady=4)
        self._preset_btns = {}
        preset_colors = {
            'Auto':        ('#30363d', TEXT),
            'Eco':         ('#1f4e2a', GREEN),
            'Normal':      ('#1a3a5c', ACCENT),
            'Performance': ('#4a3000', YELLOW),
            'Max':         ('#4a1500', RED),
        }
        for name, rpm in [('Auto', 0), ('Eco', 1200),
                          ('Normal', 2500), ('Performance', 4000), ('Max', 6200)]:
            bg_c, fg_c = preset_colors.get(name, (CARD, TEXT))
            sub = 'auto' if rpm == 0 else '{} RPM'.format(rpm)
            btn = tk.Button(
                preset_row,
                text='{}\n{}'.format(name, sub),
                bg=bg_c, fg=fg_c, relief='flat', padx=14, pady=10,
                font=('SF Pro Display', 10, 'bold'),
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
                 font=('SF Pro Display', 11)).pack(side='left')
        self.fc_man_rpm_var = tk.IntVar(value=2500)
        tk.Scale(man_row, from_=0, to=6200, variable=self.fc_man_rpm_var,
                 orient='horizontal', length=220, bg=CARD, fg=TEXT,
                 troughcolor='#21262d', highlightthickness=0,
                 activebackground=ACCENT, resolution=100).pack(side='left', padx=6)
        self.fc_man_rpm_lbl = tk.Label(man_row, text='2500 RPM', bg=BG, fg=ACCENT,
                                       font=('SF Pro Display', 11, 'bold'))
        self.fc_man_rpm_lbl.pack(side='left')
        self.fc_man_rpm_var.trace('w', self._fc_update_man_lbl)

        # Apply / Reset buttons
        btn_row = tk.Frame(inner, bg=BG)
        btn_row.pack(anchor='w', padx=36, pady=8)
        self.fc_apply_btn = tk.Button(
            btn_row, text='Apply', bg=ACCENT, fg=BG, relief='flat',
            padx=20, pady=7, font=('SF Pro Display', 11, 'bold'),
            activebackground='#79c0ff', activeforeground=BG, cursor='hand2',
            command=self._fc_apply_manual)
        self.fc_apply_btn.pack(side='left', padx=(0, 10))
        self.fc_reset_btn = tk.Button(
            btn_row, text='Reset to Auto', bg='#1a3a2a', fg=GREEN, relief='flat',
            padx=20, pady=7, font=('SF Pro Display', 11, 'bold'),
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
                     bg=BG, fg=RED, font=('SF Pro Display', 11, 'bold')).pack(anchor='w')
            tk.Label(note,
                     text='Re-clone the repo or copy smc_tool next to dashboard.py.',
                     bg=BG, fg=DIM, font=('SF Pro Display', 10)).pack(anchor='w', pady=2)

        tk.Frame(inner, bg=BG, height=24).pack()   # bottom padding

        # Disable controls if tool not available
        if not fc.available:
            self._fc_set_controls_state('disabled')

    def _build_settings_tab(self):
        tab = tk.Frame(self.nb, bg=BG)
        self.nb.add(tab, text='  Settings  ')

        inner = tk.Frame(tab, bg=BG)
        inner.pack(padx=40, pady=28, anchor='nw')

        # Alert section
        tk.Label(inner, text='Temperature Alerts', bg=BG, fg=TEXT,
                 font=('SF Pro Display', 14, 'bold')).pack(anchor='w', pady=(0, 14))

        tk.Checkbutton(inner, text='Enable alerts when temperature exceeds threshold',
                       variable=self.alert_enabled, bg=BG, fg=TEXT,
                       selectcolor=CARD, activebackground=BG, activeforeground=TEXT,
                       font=('SF Pro Display', 12),
                       command=self._apply_alert_settings).pack(anchor='w', pady=2)

        row = tk.Frame(inner, bg=BG)
        row.pack(anchor='w', pady=10)
        tk.Label(row, text='Alert at:', bg=BG, fg=DIM,
                 font=('SF Pro Display', 12)).pack(side='left', padx=(0, 10))
        self.alert_scale = tk.Scale(
            row, from_=50, to=100, variable=self.temp_alert_var,
            orient='horizontal', length=220, bg=CARD, fg=TEXT,
            troughcolor='#21262d', highlightthickness=0,
            activebackground=ACCENT, command=self._apply_alert_settings)
        self.alert_scale.pack(side='left')
        self.alert_val_lbl = tk.Label(row, text='80°C', bg=BG, fg=ORANGE,
                                      font=('SF Pro Display', 12, 'bold'))
        self.alert_val_lbl.pack(side='left', padx=10)

        tk.Frame(inner, bg=BORDER, height=1, width=440).pack(anchor='w', pady=18)

        # System info section
        tk.Label(inner, text='System Info', bg=BG, fg=TEXT,
                 font=('SF Pro Display', 14, 'bold')).pack(anchor='w', pady=(0, 12))
        self.sys_info_lbl = tk.Label(inner, text='', bg=BG, fg=DIM,
                                     font=('SF Pro Display', 11), justify='left')
        self.sys_info_lbl.pack(anchor='w')
        self._refresh_sys_info()

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
        self.g_fan.set_value(data['fan'], fc)
        self.g_mem.set_value(data['mem'], ACCENT)

        self.c_freq.update(f"{data['cpu_freq']:.0f} MHz",
                           f"CPU load: {data['cpu']:.1f}%")
        self.c_temp.update(f"{data['temp']:.1f}°C",
                           f"source: {data.get('temp_source', '?')}",
                           color=tc)

        fan_pct = int(data['fan'] / max(data['fan_max'], 1) * 100)
        self.c_fan.update(f"{data['fan']:,} RPM",
                          f"{fan_pct}% of max {data['fan_max']:,}")

        vm = psutil.virtual_memory()
        used = (vm.total - vm.available) / 1024 ** 3
        total = vm.total / 1024 ** 3
        self.c_mem.update(f"{used:.1f} GB",
                          f"of {total:.1f} GB  ({data['mem']:.0f}%)")

        self.info_lbl.configure(
            text=f"Last updated: {data.get('timestamp', '—')}  ·  Interval: 2s"
        )

        # Fan control status update
        if self.nb.index('current') == 2:
            self._fc_update_loop()

        # Update graphs only when that tab is visible
        if self.nb.index('current') == 1 and HAS_MPL:
            self._update_graphs(hist)

        self.root.after(2000, self._update_loop)

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
            for coll in ax.collections:
                coll.remove()
            ax.fill_between(x, data, alpha=0.12, color=fill_color)

        # Keep alert line in sync
        self._alert_line.set_ydata([self.monitor.temp_alert,
                                     self.monitor.temp_alert])
        self.mpl_canvas.draw_idle()

    # ── Run ───────────────────────────────────────────────────────────────────

    def run(self):
        self.root.protocol('WM_DELETE_WINDOW', self._on_close)
        self.root.mainloop()

    def _on_close(self):
        self.monitor.stop()
        try:
            self._menubar_proc.terminate()
        except Exception:
            pass
        self.root.destroy()


if __name__ == '__main__':
    DashboardApp().run()
