#!/bin/bash
# setup.sh — run once on a new Mac
# Usage: cd ~/Desktop/FanCooler && bash setup.sh

set -e
PROJECT="$(cd "$(dirname "$0")" && pwd)"
echo "=== FanCooler setup === ($PROJECT)"

# ── 1. Find Python 3 ──────────────────────────────────────────────────────────
PYTHON=""
for c in python3 python3.12 python3.11 python3.10 python3.9 python3.8; do
    if command -v "$c" &>/dev/null; then PYTHON=$(command -v "$c"); break; fi
done
[ -z "$PYTHON" ] && { echo "ERROR: Python 3 not found. Install from python.org or brew install python3"; exit 1; }
echo "Python: $PYTHON ($($PYTHON --version 2>&1))"

# ── 2. Install packages ────────────────────────────────────────────────────────
echo "Installing packages..."
"$PYTHON" -m pip install --user psutil matplotlib rumps pyobjc-framework-Cocoa \
    || echo "(pip warnings — usually ok)"

# ── 3. Compile smc_tool ────────────────────────────────────────────────────────
if [ ! -x "$PROJECT/smc_tool" ] && [ -f "$PROJECT/smc.c" ]; then
    echo "Compiling smc_tool..."
    gcc -o "$PROJECT/smc_tool" "$PROJECT/smc.c" \
        -framework IOKit -framework CoreFoundation -DCMD_TOOL_BUILD \
        && chmod +x "$PROJECT/smc_tool" && echo "  ok" \
        || echo "  WARNING: compile failed — fan control unavailable"
fi

# ── 4. Build .app ─────────────────────────────────────────────────────────────
bash "$PROJECT/build_app.sh"
