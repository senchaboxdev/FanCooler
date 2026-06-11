#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FanCooler menu bar app -- runs in the Mac menu bar."""
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


class FanCoolerBar(rumps.App):
    def __init__(self):
        super(FanCoolerBar, self).__init__('Fan', quit_button=None)

        self.temp_item = rumps.MenuItem('Temp: --')
        self.fan_item  = rumps.MenuItem('Fan:  --')
        self.cpu_item  = rumps.MenuItem('CPU:  --')

        self.menu = [
            rumps.MenuItem('FanCooler'),
            None,
            self.temp_item,
            self.fan_item,
            self.cpu_item,
            None,
            rumps.MenuItem('Open Dashboard', callback=self.open_dashboard),
            None,
            rumps.MenuItem('Quit', callback=rumps.quit_application),
        ]
        self.menu['FanCooler'].set_callback(None)

        self._dash_proc = None
        rumps.Timer(self._refresh, 1).start()

    def _refresh(self, _=None):
        try:
            if not os.path.exists(STATE_FILE):
                return
            # Stale state = dashboard not running (crashed or quit)
            if time.time() - os.path.getmtime(STATE_FILE) > 10:
                self.title = 'Fan --'
                self.temp_item.title = 'Temp: -- (dashboard not running)'
                self.fan_item.title  = 'Fan:  --'
                self.cpu_item.title  = 'CPU:  --'
                return
            with open(STATE_FILE) as f:
                data = json.load(f)

            temp = data.get('temp', 0.0)
            fan  = data.get('fan', 0)
            cpu  = data.get('cpu', 0.0)
            fans = data.get('fans') or []

            self.temp_item.title = 'Temp: {:.1f}°C'.format(temp)
            if len(fans) >= 2:
                self.fan_item.title = 'Fan:  {:,} / {:,} RPM'.format(
                    fans[0][0], fans[1][0])
            else:
                self.fan_item.title = 'Fan:  {:,} RPM'.format(fan)
            self.cpu_item.title  = 'CPU:  {:.1f}%'.format(cpu)

            if temp >= 80:
                status = 'HOT'
            elif temp >= 70:
                status = 'WRM'
            else:
                status = 'Fan'
            self.title = '{} {:.0f}°'.format(status, temp)
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
    FanCoolerBar().run()
