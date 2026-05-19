#!/usr/bin/env python3
import tkinter as tk
from tkinter import ttk, messagebox
import psutil
import subprocess
import platform
import math

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
class DashboardApp:
    def __init__(self):
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
        self._update_loop()

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

        for ax in (self.ax_cpu, self.ax_temp, self.ax_fan):
            ax.set_facecolor(CARD)
            ax.grid(True, alpha=0.3, color=BORDER)
            for sp in ax.spines.values():
                sp.set_color(BORDER)

        self.mpl_canvas = FigureCanvasTkAgg(self.fig, master=tab)
        self.mpl_canvas.draw()
        self.mpl_canvas.get_tk_widget().pack(fill='both', expand=True, padx=4, pady=4)

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

        # Update graphs only when that tab is visible
        if self.nb.index('current') == 1 and HAS_MPL:
            self._update_graphs(hist)

        self.root.after(2000, self._update_loop)

    def _update_graphs(self, hist):
        if not hist['cpu']:
            return
        x = range(len(hist['cpu']))

        for ax, key, color, label, ylim in [
            (self.ax_cpu,  'cpu',  ACCENT,  'CPU %',   (0, 100)),
            (self.ax_temp, 'temp', ORANGE,  'Temp °C', None),
            (self.ax_fan,  'fan',  BLUE,    'Fan RPM', (0, 6200)),
        ]:
            ax.clear()
            ax.set_facecolor(CARD)
            ax.grid(True, alpha=0.3, color=BORDER)
            for sp in ax.spines.values():
                sp.set_color(BORDER)
            ax.tick_params(colors=DIM, labelsize=8)
            ax.set_ylabel(label, fontsize=9, color=DIM)

            if hist[key]:
                ax.plot(x, hist[key], color=color, linewidth=2, solid_capstyle='round')
                ax.fill_between(x, hist[key], alpha=0.12, color=color)
            if ylim:
                ax.set_ylim(*ylim)

        # Alert line on temp graph
        self.ax_temp.axhline(y=self.monitor.temp_alert,
                             color=RED, linestyle='--', alpha=0.5, linewidth=1.2)

        self.mpl_canvas.draw_idle()

    # ── Run ───────────────────────────────────────────────────────────────────

    def run(self):
        self.root.protocol('WM_DELETE_WINDOW', self._on_close)
        self.root.mainloop()

    def _on_close(self):
        self.monitor.stop()
        self.root.destroy()


if __name__ == '__main__':
    DashboardApp().run()
