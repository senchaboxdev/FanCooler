#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ClaudeCooler menu bar app -- runs in the Mac menu bar."""
import subprocess
import sys
import os
import json
import time
import fcntl

# Single instance — main.py and dashboard.py may both try to spawn us
_lock_fh = open('/tmp/fancooler_menubar.lock', 'w')
try:
    fcntl.flock(_lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
except IOError:
    sys.exit(0)

# Must be set BEFORE rumps/NSApplication initialises — prevents Dock entry
try:
    from AppKit import NSApplication
    NSApplication.sharedApplication().setActivationPolicy_(1)  # Accessory
except Exception:
    pass

try:
    import rumps
except ImportError:
    print("rumps not installed. Run: pip install rumps")
    sys.exit(1)

STATE_FILE = '/tmp/fancooler_state.json'
BASE = os.path.dirname(os.path.abspath(__file__))

FIGSP = u' '  # figure space (U+2007) — pads numerals without visual jitter


def _find_icon():
    """Locate the monochrome template glyph; None = text-only fallback."""
    for p in (os.path.join(BASE, 'menubar_icon.png'),
              '/tmp/fancooler_menubar.png'):
        if os.path.exists(p):
            return p
    return None


class ClaudeCoolerBar(rumps.App):
    def __init__(self):
        icon = _find_icon()
        try:
            super(ClaudeCoolerBar, self).__init__(
                'ClaudeCooler', icon=icon, template=True, quit_button=None)
        except TypeError:  # very old rumps without template kwarg
            super(ClaudeCoolerBar, self).__init__(
                'ClaudeCooler', icon=icon, quit_button=None)
        self._has_icon = icon is not None
        self._set_status_title(None)

        self.header    = rumps.MenuItem('ClaudeCooler — Thermal Monitor')
        self.temp_item = rumps.MenuItem('Temperature   --')
        self.fan_item  = rumps.MenuItem('Fan speed     --')
        self.cpu_item  = rumps.MenuItem('CPU load      --')

        self.menu = [
            self.header,
            None,
            self.temp_item,
            self.fan_item,
            self.cpu_item,
            None,
            rumps.MenuItem('Open Dashboard', callback=self.open_dashboard),
            None,
            rumps.MenuItem('Quit ClaudeCooler', callback=rumps.quit_application),
        ]
        self.header.set_callback(None)  # disabled header line

        self._dash_proc = None
        rumps.Timer(self._refresh, 1).start()

    def _set_status_title(self, temp):
        """Glanceable status-bar title: icon + padded temp, with tasteful
        escalation markers ('⚠' >= 70, '🔥' >= 80)."""
        if temp is None:
            txt = '--°'
        elif temp >= 80:
            txt = '🔥{:{f}>2.0f}°'.format(temp, f=FIGSP)
        elif temp >= 70:
            txt = '⚠{:{f}>2.0f}°'.format(temp, f=FIGSP)
        else:
            txt = '{:{f}>2.0f}°'.format(temp, f=FIGSP)
        # leading space separates text from the glyph; text-only gets a label
        self.title = ' ' + txt if self._has_icon else 'Fan ' + txt

    def _refresh(self, _=None):
        try:
            if not os.path.exists(STATE_FILE):
                return
            # Stale state = dashboard not running (crashed or quit)
            if time.time() - os.path.getmtime(STATE_FILE) > 10:
                self._set_status_title(None)
                self.temp_item.title = 'Dashboard not running'
                self.fan_item.title  = 'Fan speed     --'
                self.cpu_item.title  = 'CPU load      --'
                return
            with open(STATE_FILE) as f:
                data = json.load(f)

            temp = data.get('temp', 0.0)
            fan  = data.get('fan', 0)
            cpu  = data.get('cpu', 0.0)
            fans = data.get('fans') or []

            self.temp_item.title = 'Temperature   {:{f}>5.1f} °C'.format(
                temp, f=FIGSP)
            if len(fans) >= 2:
                self.fan_item.title = 'Fan speed     {:{f}>5,} / {:{f}>5,} RPM'.format(
                    fans[0][0], fans[1][0], f=FIGSP)
            else:
                self.fan_item.title = 'Fan speed     {:{f}>5,} RPM'.format(
                    fan, f=FIGSP)
            self.cpu_item.title = 'CPU load      {:{f}>5.1f} %'.format(
                cpu, f=FIGSP)

            self._set_status_title(temp)
        except Exception:
            pass

    def open_dashboard(self, _):
        if self._dash_proc and self._dash_proc.poll() is None:
            subprocess.run(
                ['osascript', '-e',
                 'tell application "System Events" to set frontmost of '
                 '(first process whose unix id is {}) to true'.format(
                     self._dash_proc.pid)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=2
            )
            return
        self._dash_proc = subprocess.Popen(
            [sys.executable, os.path.join(BASE, 'dashboard.py')]
        )


if __name__ == '__main__':
    ClaudeCoolerBar().run()
