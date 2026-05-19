import psutil
import subprocess
import threading
import json
import re
import os
import shutil
from collections import deque
from datetime import datetime

STATE_FILE = '/tmp/fancooler_state.json'
HISTORY_SIZE = 60


# ── Fan Controller ────────────────────────────────────────────────────────────

class FanController:
    """
    Controls Mac fan speed via smcFanControl CLI (Intel Macs).
    Supports auto-boost: when temp > threshold, raise min RPM automatically.
    """

    # Ordered list of tool locations to try
    TOOL_CANDIDATES = [
        '/Applications/smcFanControl.app/Contents/Resources/smcFanControl',
        '/usr/local/bin/smcFanControl',
        '/opt/homebrew/bin/smcFanControl',
    ]

    PRESETS = {
        'Auto':        0,
        'Eco':         1200,
        'Normal':      2500,
        'Performance': 4000,
        'Max':         6200,
    }

    def __init__(self):
        self.tool_path   = self._detect_tool()
        self.auto_boost  = False
        self.boost_thresh = 75.0   # °C — start boosting above this
        self.boost_rpm   = 4000    # RPM to set when boosting
        self._boosted    = False
        self._lock       = threading.Lock()
        self.status_msg  = ''      # last action result message

    def _detect_tool(self):
        for p in self.TOOL_CANDIDATES:
            if os.path.isfile(p) and os.access(p, os.X_OK):
                return p
        found = shutil.which('smcFanControl')
        return found  # None if not found

    @property
    def available(self):
        return self.tool_path is not None

    def set_min_rpm(self, rpm, fan_nr=0):
        """Set minimum fan RPM for fan_nr.  Returns (ok, message)."""
        if not self.available:
            return False, 'smcFanControl not installed'
        rpm = max(0, int(rpm))
        try:
            r = subprocess.Popen(
                [self.tool_path,
                 '--setMinRpm', str(rpm),
                 '--startFanNr', str(fan_nr)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            out, err = r.communicate(timeout=5)
            ok = r.returncode == 0
            msg = (out + err).decode('utf-8', 'ignore').strip()
            with self._lock:
                self.status_msg = ('Boosted to {} RPM'.format(rpm)
                                   if ok else 'Error: ' + msg[:60])
            return ok, msg
        except Exception as e:
            return False, str(e)

    def reset_auto(self):
        """Reset fan to macOS automatic control (min RPM = 0)."""
        ok, msg = self.set_min_rpm(0)
        if ok:
            with self._lock:
                self.status_msg = 'Reset to Auto'
                self._boosted = False
        return ok, msg

    def apply_preset(self, name):
        rpm = self.PRESETS.get(name, 0)
        if name == 'Auto':
            return self.reset_auto()
        return self.set_min_rpm(rpm)

    def auto_check(self, temp):
        """Call from monitor loop — auto-boost fan if temp is high."""
        if not self.auto_boost or not self.available:
            return
        if temp >= self.boost_thresh and not self._boosted:
            ok, _ = self.set_min_rpm(self.boost_rpm)
            if ok:
                with self._lock:
                    self._boosted = True
        elif temp < (self.boost_thresh - 5) and self._boosted:
            ok, _ = self.reset_auto()

    def install_brew(self, on_done=None):
        """Run brew install --cask smcfancontrol in background thread."""
        def _run():
            try:
                r = subprocess.Popen(
                    ['brew', 'install', '--cask', 'smcfancontrol'],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                out, err = r.communicate(timeout=300)
                ok = r.returncode == 0
                # Re-detect after install
                self.tool_path = self._detect_tool()
                if on_done:
                    on_done(ok, (out + err).decode('utf-8', 'ignore').strip())
            except Exception as e:
                if on_done:
                    on_done(False, str(e))
        t = threading.Thread(target=_run, daemon=True)
        t.start()


# ── System Monitor ────────────────────────────────────────────────────────────

class SystemMonitor:
    def __init__(self):
        self.history = {
            'cpu':  deque(maxlen=HISTORY_SIZE),
            'temp': deque(maxlen=HISTORY_SIZE),
            'fan':  deque(maxlen=HISTORY_SIZE),
            'mem':  deque(maxlen=HISTORY_SIZE),
        }
        self.current = {
            'cpu': 0.0,
            'cpu_freq': 0.0,
            'mem': 0.0,
            'temp': 0.0,
            'fan': 0,
            'fan_max': 6000,
            'temp_source': 'estimated',
            'fan_source': 'estimated',
            'timestamp': '',
        }
        self._lock = threading.Lock()
        self._running = False
        self._thread = None
        self.on_high_temp = None
        self.temp_alert = 80.0
        self._last_alert_time = 0

        self.fan_ctrl = FanController()  # fan controller instance

    def start(self):
        psutil.cpu_percent(interval=None)  # warm-up call
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def _loop(self):
        import time
        while self._running:
            self._update()
            time.sleep(2)

    def _update(self):
        import time as t
        cpu = psutil.cpu_percent(interval=None)
        freq = psutil.cpu_freq()
        cpu_freq = freq.current if freq else 0.0
        mem = psutil.virtual_memory().percent
        temp, temp_source = self._read_temp()
        fan, fan_max, fan_source = self._read_fan(temp)
        ts = datetime.now().strftime('%H:%M:%S')

        with self._lock:
            self.current.update({
                'cpu': cpu,
                'cpu_freq': cpu_freq,
                'mem': mem,
                'temp': temp,
                'fan': fan,
                'fan_max': fan_max,
                'temp_source': temp_source,
                'fan_source': fan_source,
                'timestamp': ts,
            })
            self.history['cpu'].append(cpu)
            self.history['temp'].append(temp)
            self.history['fan'].append(fan)
            self.history['mem'].append(mem)

        self._save_state()

        # Auto fan boost check
        self.fan_ctrl.auto_check(temp)

        if self.on_high_temp and temp >= self.temp_alert:
            if t.time() - self._last_alert_time > 60:
                self._last_alert_time = t.time()
                self.on_high_temp(temp)

    def _read_temp(self):
        # Method 1: psutil
        try:
            temps = psutil.sensors_temperatures()
            if temps:
                for key in ['coretemp', 'cpu_thermal', 'cpu-thermal', 'k10temp', 'acpitz']:
                    if key in temps and temps[key]:
                        return temps[key][0].current, 'psutil'
                first_key = next(iter(temps))
                if temps[first_key]:
                    return temps[first_key][0].current, 'psutil:{}'.format(first_key)
        except Exception:
            pass

        # Method 2: osx-cpu-temp (brew install osx-cpu-temp)
        try:
            r = subprocess.Popen(['osx-cpu-temp'],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            out, _ = r.communicate(timeout=2)
            if r.returncode == 0:
                m = re.search(r'(\d+\.?\d*)\s*\xb0?C',
                              out.decode('utf-8', errors='ignore'))
                if m:
                    return float(m.group(1)), 'osx-cpu-temp'
        except Exception:
            pass

        # Method 3: istats (sudo gem install iStats)
        try:
            r = subprocess.Popen(['istats', 'cpu', '--value-only'],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            out, _ = r.communicate(timeout=2)
            val = out.decode('utf-8', errors='ignore').strip()
            if r.returncode == 0 and val:
                return float(val), 'istats'
        except Exception:
            pass

        # Fallback: estimate from CPU load
        cpu = psutil.cpu_percent(interval=None)
        temp = round(35.0 + (cpu / 100.0) * 50.0, 1)
        return temp, 'estimated'

    def _read_fan(self, temp):
        # Try smcFanControl for actual reading
        if self.fan_ctrl.available:
            try:
                r = subprocess.Popen(
                    [self.fan_ctrl.tool_path, '--getFanRpm', '--startFanNr', '0'],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                out, _ = r.communicate(timeout=2)
                m = re.search(r'(\d+)', out.decode('utf-8', 'ignore'))
                if m:
                    return int(m.group(1)), 6200, 'smcFanControl'
            except Exception:
                pass

        # Estimate from temperature
        if temp < 45:
            speed = 1200
        elif temp < 60:
            speed = int(1200 + (temp - 45) * 80)
        elif temp < 75:
            speed = int(2400 + (temp - 60) * 120)
        else:
            speed = int(4200 + (temp - 75) * 144)
        return min(speed, 6000), 6000, 'estimated'

    def get_current(self):
        with self._lock:
            return dict(self.current)

    def get_history(self):
        with self._lock:
            return {k: list(v) for k, v in self.history.items()}

    def _save_state(self):
        try:
            with self._lock:
                state = dict(self.current)
            with open(STATE_FILE, 'w') as f:
                json.dump(state, f)
        except Exception:
            pass

    @staticmethod
    def load_state():
        try:
            if os.path.exists(STATE_FILE):
                with open(STATE_FILE) as f:
                    return json.load(f)
        except Exception:
            pass
        return None
