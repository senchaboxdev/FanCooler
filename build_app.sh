#!/bin/bash
# build_app.sh — build FanCooler.app next to this script (or on Desktop)
# Called by setup.sh or run directly: bash build_app.sh

set -e
PROJECT="$(cd "$(dirname "$0")" && pwd)"
APP="$(dirname "$PROJECT")/FanCooler.app"   # sibling of FanCooler/ folder
echo "Building $APP ..."

# ── Find Python (for icon generation) ────────────────────────────────────────
PYTHON=""
for c in python3 python3.12 python3.11 python3.10 python3.9 python3.8 python3.6; do
    if command -v "$c" &>/dev/null; then PYTHON=$(command -v "$c"); break; fi
done
[ -z "$PYTHON" ] && { echo "ERROR: Python 3 not found"; exit 1; }

# ── Bundle structure ──────────────────────────────────────────────────────────
mkdir -p "$APP/Contents/MacOS"
mkdir -p "$APP/Contents/Resources"

# ── Compile native launcher binary ────────────────────────────────────────────
echo "  Compiling launcher..."
cc -o "$APP/Contents/MacOS/FanCooler" "$PROJECT/launcher.c"
chmod +x "$APP/Contents/MacOS/FanCooler"

# ── Info.plist ────────────────────────────────────────────────────────────────
cat > "$APP/Contents/Info.plist" << 'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>             <string>FanCooler</string>
    <key>CFBundleDisplayName</key>      <string>FanCooler</string>
    <key>CFBundleIdentifier</key>       <string>com.senchabox.fancooler</string>
    <key>CFBundleVersion</key>          <string>1.0</string>
    <key>CFBundleShortVersionString</key><string>1.0</string>
    <key>CFBundleExecutable</key>       <string>FanCooler</string>
    <key>CFBundlePackageType</key>      <string>APPL</string>
    <key>CFBundleSignature</key>        <string>????</string>
    <key>CFBundleIconFile</key>         <string>AppIcon</string>
    <key>NSHighResolutionCapable</key>  <true/>
    <key>NSAppleEventsUsageDescription</key>
        <string>FanCooler uses AppleScript to control fan speed.</string>
</dict>
</plist>
PLIST

# ── Icon ──────────────────────────────────────────────────────────────────────
echo "  Building icon..."
ICONSET="/tmp/FanCooler_$$.iconset"
mkdir -p "$ICONSET"
"$PYTHON" "$PROJECT/make_icon.py"
for pair in "16:icon_16x16" "32:icon_16x16@2x" "32:icon_32x32" \
            "64:icon_32x32@2x" "128:icon_128x128" "256:icon_128x128@2x" \
            "256:icon_256x256" "512:icon_256x256@2x" "512:icon_512x512" \
            "1024:icon_512x512@2x"; do
    sz="${pair%%:*}"; name="${pair##*:}"
    cp "/tmp/icon_${sz}.png" "$ICONSET/${name}.png"
done
iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/AppIcon.icns"
rm -rf "$ICONSET"

# ── Remove quarantine ─────────────────────────────────────────────────────────
xattr -cr "$APP"

echo ""
echo "Done!  $APP"
echo "Double-click it to launch, or drag to Dock."
