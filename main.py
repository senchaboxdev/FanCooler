#!/usr/bin/env python3
"""
FanCooler — entry point.
Starts the dashboard window AND the menu bar app simultaneously.
"""
import subprocess
import sys
import os
import signal

BASE = os.path.dirname(os.path.abspath(__file__))


def main():
    procs = []

    def cleanup(*_):
        for p in procs:
            try:
                p.terminate()
            except Exception:
                pass
        sys.exit(0)

    signal.signal(signal.SIGINT,  cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    # Launch dashboard (foreground window).
    # The dashboard spawns the menu bar app itself — don't spawn it here too,
    # or we end up with two menu bar icons.
    dashboard = subprocess.Popen([sys.executable, os.path.join(BASE, 'dashboard.py')])
    procs.append(dashboard)

    # Keep alive until dashboard closes
    try:
        dashboard.wait()
    except KeyboardInterrupt:
        pass
    finally:
        cleanup()


if __name__ == '__main__':
    main()
