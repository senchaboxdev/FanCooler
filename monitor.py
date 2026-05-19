import psutil
import subprocess
import threading
import json
import re
import os
from collections import deque
from datetime import datetime

STATE_FILE = '/tmp/fancooler_state.json'
HISTORY_SIZE = 60


class SystemMonitor:
    def __init__(self):
        self.history = {
            'cpu': deque(maxlen=HISTORY_SIZE),
            'temp': deque(maxlen=HISTORY_SIZE),
            'fan': deque(maxlen=HISTORY_SIZE),
            'mem': deque(maxlen=HISTORY_SIZE),
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
                    return temps[first_key][0].current, f'psutil:{first_key}'
        except Exception:
            pass

        # Method 2: osx-cpu-temp (brew install osx-cpu-temp)
        try:
            r = subprocess.run(['osx-cpu-temp'],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               timeout=2)
            if r.returncode == 0:
                m = re.search(r'(\d+\.?\d*)\s*\xb0?C', r.stdout.decode('utf-8', errors='ignore'))
                if m:
                    return float(m.group(1)), 'osx-cpu-temp'
        except Exception:
            pass

        # Method 3: istats (sudo gem install iStats)
        try:
            r = subprocess.run(['istats', 'cpu', '--value-only'],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               timeout=2)
            out = r.stdout.decode('utf-8', errors='ignore').strip()
            if r.returncode == 0 and out:
                return float(out), 'istats'
        except Exception:
            pass

        # Fallback: estimate from CPU load
        cpu = psutil.cpu_percent(interval=None)
        temp = round(35.0 + (cpu / 100.0) * 50.0, 1)
        return temp, 'estimated'

    def _read_fan(self, temp):
        # Method 1: psutil fans
        try:
            fans = psutil.sensors_fans()
            if fans:
                for entries in fans.values():
                    if entries:
                        high = entries[0].high or 6000
                        return int(entries[0].current), int(high), 'psutil'
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
