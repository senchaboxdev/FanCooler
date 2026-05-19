#!/bin/bash
set -e
echo "🌀 FanCooler Setup"
echo "=================="

# Check Python 3
if ! command -v python3 &>/dev/null; then
  echo "❌ Python 3 not found. Install from https://python.org"
  exit 1
fi

echo "✓ Python $(python3 --version)"

# Install dependencies
echo ""
echo "Installing dependencies..."
python3 -m pip install --upgrade pip -q
python3 -m pip install psutil matplotlib rumps Pillow

echo ""
echo "✅ Setup complete!"
echo ""
echo "Run the app:"
echo "  python3 main.py          ← dashboard + menu bar"
echo "  python3 dashboard.py     ← dashboard only"
echo "  python3 menubar.py       ← menu bar only"
echo ""
echo "Optional: for real temperature readings, install one of:"
echo "  brew install osx-cpu-temp"
echo "  sudo gem install iStats"
