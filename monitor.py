import psutil
import subprocess
import threading
import json
import re
import os
from collections import deque
from datetime import datetime

STATE_FILE    = '/tmp/fancooler_state.json'
SUDOERS_FILE  = '/etc/sudoers.d/fancooler'
HISTORY_SIZE  = 60
_HERE         = os.path.dirname(os.path.abspath(__file__))


# ── Fan Controller ────────────────────────────────────────────────────────────

class FanController:
    """
    Controls Intel Mac fan speed via the bundled smc_tool binary (IOKit).
    Fan writes require admin — shown via macOS password dialog (AppleScript).
    Supports auto-boost: when temp > threshold, raise min RPM automatically.
    """

    PRESETS = {
        'Auto':        None,   # restore hardware defaults
        'Eco':         1400,
        'Normal':      2500,
        'Performance': 4000,
        'Max':         6000,
    }

    def __init__(self):
        self._smc         = os.path.join(_HERE, 'smc_tool')
        self.auto_boost   = False
        self.boost_thresh = 75.0
        self.boost_rpm    = 4000
        self._boosted     = False
        self._lock        = threading.Lock()
        self.status_msg   = ''
        self._hw_min      = self._read_hw_min()   # hardware-default min bytes

    @property
    def available(self):
        return os.path.isfile(self._smc) and os.access(self._smc, os.X_OK)

    @property
    def is_setup(self):
        """True if the NOPASSWD sudoers rule is in place and works."""
        if not os.path.exists(SUDOERS_FILE):
            return False
        try:
            r = subprocess.Popen(
                ['sudo', '-n', self._smc, '-f'],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            _, err = r.communicate(timeout=3)
            # success OR error not about password = rule is active
            return b'password' not in err.lower()
        except Exception:
            return False

    def setup_sudoers(self, on_done=None):
        """One-time setup: write NOPASSWD sudoers rule via osascript.
        After this, all fan commands run silently with 'sudo -n'.
        """
        import tempfile
        user = os.environ.get('USER') or os.environ.get('LOGNAME') or 'root'
        rule = '{} ALL=(ALL) NOPASSWD: {}'.format(user, self._smc)

        def _run():
            sh = '#!/bin/sh\necho "{r}" > {f}\nchmod 440 {f}\n'.format(
                r=rule, f=SUDOERS_FILE)
            fd, path = tempfile.mkstemp(suffix='.sh', prefix='/tmp/fc_setup_')
            try:
                os.write(fd, sh.encode('ascii'))
                os.close(fd)
                os.chmod(path, 0o755)
                as_cmd = ('do shell script "{}" '
                          'with administrator privileges').format(path)
                r = subprocess.Popen(['osascript', '-e', as_cmd],
                                     stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE)
                try:
                    out, err = r.communicate(timeout=30)
                except Exception:
                    r.kill()
                    out, err = r.communicate()
                ok = r.returncode == 0 and os.path.exists(SUDOERS_FILE)
                if on_done:
                    on_done(ok, (out + err).decode('utf-8', 'ignore').strip())
            finally:
                try:
                    os.unlink(path)
                except Exception:
                    pass

        threading.Thread(target=_run, daemon=True).start()

    # ── Internal helpers ──────────────────────────────────────────────────

    def _read_hw_min(self):
        """Read current F0Mn/F1Mn hex bytes as the 'auto' baseline."""
        defaults = {}
        if not self.available:
            return defaults
        try:
            for i in range(2):
                key = 'F{}Mn'.format(i)
                r = subprocess.Popen([self._smc, '-k', key, '-r'],
                                     stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE)
                out, _ = r.communicate(timeout=2)
                m = re.search(r'\(bytes ([0-9a-f ]+)\)',
                              out.decode('utf-8', 'ignore'))
                if m:
                    defaults[i] = m.group(1).replace(' ', '')
        except Exception:
            pass
        return defaults

    @staticmethod
    def _rpm_to_hex(rpm):
        """Convert RPM to 4-byte little-endian IEEE-754 float hex string."""
        import struct
        return struct.pack('<f', float(rpm)).hex()

    def _run_admin(self, sh_lines):
        """Run smc commands with root. Uses 'sudo -n' (silent) when the
        sudoers rule is in place; otherwise shows macOS password dialog once.
        """
        import tempfile

        if self.is_setup:
            # Silent path — no dialog
            combined_out = ''
            ok = True
            for line in sh_lines:
                cmd = ['sudo', '-n'] + line.split()
                r = subprocess.Popen(cmd,
                                     stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE)
                out, err = r.communicate(timeout=5)
                combined_out += (out + err).decode('utf-8', 'ignore')
                if r.returncode != 0:
                    ok = False
            return ok, combined_out.strip()

        # First-time path — osascript dialog
        script_content = '#!/bin/sh\n' + '\n'.join(sh_lines) + '\n'
        fd, sh_path = tempfile.mkstemp(suffix='.sh', prefix='/tmp/fc_')
        try:
            os.write(fd, script_content.encode('ascii'))
            os.close(fd)
            os.chmod(sh_path, 0o755)
            as_cmd = ('do shell script "{}" '
                      'with administrator privileges').format(sh_path)
            r = subprocess.Popen(['osascript', '-e', as_cmd],
                                 stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE)
            try:
                out, err = r.communicate(timeout=30)
            except Exception:
                r.kill()
                out, err = r.communicate()
            return r.returncode == 0, (out + err).decode('utf-8', 'ignore').strip()
        finally:
            try:
                os.unlink(sh_path)
            except Exception:
                pass

    # ── Public API ────────────────────────────────────────────────────────

    def set_min_rpm(self, rpm):
        """Set minimum RPM for all fans. Returns (ok, msg)."""
        if not self.available:
            return False, 'smc_tool not found'
        h = self._rpm_to_hex(rpm)
        ok, msg = self._run_admin([
            '{} -k F0Mn -w {}'.format(self._smc, h),
            '{} -k F1Mn -w {}'.format(self._smc, h),
        ])
        with self._lock:
            self.status_msg = ('Set to {} RPM'.format(int(rpm))
                               if ok else 'Auth cancelled or failed')
        return ok, msg

    def reset_auto(self):
        """Restore hardware-default minimum RPM (auto control)."""
        if not self.available:
            return False, 'smc_tool not found'
        hw = self._hw_min
        ok, msg = self._run_admin([
            '{} -k F0Mn -w {}'.format(self._smc, hw.get(0, '00409c44')),
            '{} -k F1Mn -w {}'.format(self._smc, hw.get(1, '00c0a844')),
        ])
        with self._lock:
            self.status_msg = 'Reset to Auto' if ok else 'Reset failed'
            if ok:
                self._boosted = False
        return ok, msg

    def apply_preset(self, name):
        rpm = self.PRESETS.get(name)
        return self.reset_auto() if rpm is None else self.set_min_rpm(rpm)

    def get_fan_info(self):
        """Return list of (current_rpm, min_rpm) per fan."""
        if not self.available:
            return []
        try:
            r = subprocess.Popen([self._smc, '-f'],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            out, _ = r.communicate(timeout=3)
            text = out.decode('utf-8', 'ignore')
            result = []
            for cur, mn in zip(
                re.findall(r'Current speed\s*:\s*(\d+)', text),
                re.findall(r'Minimum speed\s*:\s*(\d+)', text),
            ):
                result.append((int(cur), int(mn)))
            return result
        except Exception:
            return []

    def auto_check(self, temp):
        """Called each monitor cycle — auto-boost if temp is high."""
        if not self.auto_boost or not self.available:
            return
        if temp >= self.boost_thresh and not self._boosted:
            ok, _ = self.set_min_rpm(self.boost_rpm)
            if ok:
                with self._lock:
                    self._boosted = True
        elif temp < (self.boost_thresh - 5) and self._boosted:
            self.reset_auto()


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
        self.fan_ctrl = FanController()

    def start(self):
        psutil.cpu_percent(interval=None)
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
        cpu      = psutil.cpu_percent(interval=None)
        freq     = psutil.cpu_freq()
        cpu_freq = freq.current if freq else 0.0
        mem      = psutil.virtual_memory().percent
        temp, temp_src = self._read_temp()
        fan, fan_max, fan_src = self._read_fan()
        ts = datetime.now().strftime('%H:%M:%S')

        with self._lock:
            self.current.update({
                'cpu': cpu, 'cpu_freq': cpu_freq, 'mem': mem,
                'temp': temp, 'fan': fan, 'fan_max': fan_max,
                'temp_source': temp_src, 'fan_source': fan_src,
                'timestamp': ts,
            })
            self.history['cpu'].append(cpu)
            self.history['temp'].append(temp)
            self.history['fan'].append(fan)
            self.history['mem'].append(mem)

        self._save_state()
        self.fan_ctrl.auto_check(temp)

        if self.on_high_temp and temp >= self.temp_alert:
            if t.time() - self._last_alert_time > 60:
                self._last_alert_time = t.time()
                self.on_high_temp(temp)

    def _read_temp(self):
        # psutil
        try:
            temps = psutil.sensors_temperatures()
            if temps:
                for key in ['coretemp', 'cpu_thermal', 'cpu-thermal', 'k10temp']:
                    if key in temps and temps[key]:
                        return temps[key][0].current, 'psutil'
                first = next(iter(temps))
                if temps[first]:
                    return temps[first][0].current, 'psutil:{}'.format(first)
        except Exception:
            pass
        # osx-cpu-temp
        try:
            r = subprocess.Popen(['osx-cpu-temp'],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            out, _ = r.communicate(timeout=2)
            m = re.search(r'(\d+\.?\d*)', out.decode('utf-8', 'ignore'))
            if m and r.returncode == 0:
                return float(m.group(1)), 'osx-cpu-temp'
        except Exception:
            pass
        # istats
        try:
            r = subprocess.Popen(['istats', 'cpu', '--value-only'],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            out, _ = r.communicate(timeout=2)
            val = out.decode('utf-8', 'ignore').strip()
            if r.returncode == 0 and val:
                return float(val), 'istats'
        except Exception:
            pass
        # estimate
        cpu = psutil.cpu_percent(interval=None)
        return round(35.0 + (cpu / 100.0) * 50.0, 1), 'estimated'

    def _read_fan(self):
        # smc_tool (actual reading)
        fans = self.fan_ctrl.get_fan_info()
        if fans:
            avg_cur = sum(f[0] for f in fans) // len(fans)
            max_rpm = 6336  # MacBookPro15,2 fan max
            return avg_cur, max_rpm, 'smc_tool'
        # estimate
        temp = self.current.get('temp', 50)
        if temp < 45:
            speed = 1250
        elif temp < 60:
            speed = int(1250 + (temp - 45) * 80)
        elif temp < 75:
            speed = int(2450 + (temp - 60) * 120)
        else:
            speed = int(4250 + (temp - 75) * 140)
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
