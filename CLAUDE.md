# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

FanCooler is a fan-control and temperature-monitoring app for Intel Macs (developed on a MacBookPro15,2). Tkinter dashboard + rumps menu bar app, with SMC reads/writes done through the bundled `smc_tool` binary.

**Python 3.6 compatibility is required** — the dev machine runs Python 3.6.8 (f-strings are fine; no walrus, dataclasses, or 3.7+ stdlib).

## Commands

```bash
pip3 install -r requirements.txt        # deps: psutil, matplotlib, rumps, Pillow
python3 main.py                         # run from terminal (launches dashboard, which spawns menubar)
python3 -m py_compile main.py monitor.py dashboard.py menubar.py   # syntax check
bash build_app.sh                       # build ../FanCooler.app (Desktop)
```

There are no tests or linter. To verify monitor logic headlessly (no GUI):

```bash
python3 -c "
from monitor import SystemMonitor
m = SystemMonitor(); m._update()
print(m.get_current())"
```

**After editing any .py file, run `bash build_app.sh`** — the .app bundle contains copies of the sources (`FanCooler.app/Contents/Resources/`), so the user's installed app does not pick up repo changes until rebuilt.

## Architecture

Two processes, communicating one-way through a state file:

- **dashboard.py** — Tk GUI (gauges, matplotlib history, fan control, settings tabs). Owns the `SystemMonitor` thread and spawns `menubar.py` as a subprocess. Single-instance via `fcntl` lock on `/tmp/fancooler.lock`.
- **menubar.py** — rumps menu bar app. Reads `/tmp/fancooler_state.json` (written by the monitor every 2s); treats a file older than 10s as "dashboard not running". Its own lock: `/tmp/fancooler_menubar.lock`. Only dashboard.py spawns it — `main.py` must not, or two menu bar icons appear.
- **main.py** — thin terminal launcher (Popen dashboard.py, wait). The .app instead uses `launcher.c`, a C exec shim that finds a Python 3 and execs `dashboard.py` directly.
- **monitor.py** — all non-GUI logic: `SystemMonitor` (2s sampling loop: psutil CPU/mem + SMC temp/fan) and `FanController` (presets, manual min-RPM, auto-boost). Also home of `load_config`/`save_config` (`~/.fancooler.json` — alert + boost settings persist there).
- **smc_write.py** — unused ctypes fallback for SMC writes; kept in the bundle but nothing calls it.

## SMC access model (the part that's easy to get wrong)

- **Reads need no root.** `smc_tool -k TC0P -r` (temperature), `smc_tool -f` (per-fan current/min/max RPM), `smc_tool -t` (all temp sensors). The monitor reads real values this way; "estimated" sources are only fallbacks. The working temp key is cached in `SystemMonitor._temp_key`.
- **Writes need root.** Fan minimum RPM is set by writing `F{i}Mn` keys with a little-endian IEEE-754 float as hex (this machine's SMC uses `flt`, not the older FPE2 format). "Auto" = restoring the hardware-default min bytes captured at startup (`FanController._hw_min`).
- **Privilege path:** the one-time setup (`FanController.setup_sudoers`) copies smc_tool to a root-owned `/usr/local/libexec/fancooler-smc` and installs a NOPASSWD rule in `/etc/sudoers.d/fancooler` (validated with `visudo -cf` before install). After that, writes go through `sudo -n`. Without setup, writes fall back to an osascript admin-password dialog. **Never point the sudoers rule at the user-writable bundled binary** — that is a silent root escalation; always use the root-owned system copy (`FanController._admin_smc` picks the right path).
- Auto-boost deliberately refuses to act when setup hasn't been done (otherwise it would pop a password dialog every 2s) and backs off 60s after a failed write.

## Hardware notes

Don't hardcode fan specs: fan count, min and max RPM differ per fan (here: left max 6336, right max 6864) and are read from `smc_tool -f` at runtime. Fan writes change real hardware state; reads are always safe to run while developing.
