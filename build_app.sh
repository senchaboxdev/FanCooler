#!/bin/bash
# build_app.sh — creates FanCooler.app on the Desktop
# Run once after cloning: bash build_app.sh

set -e

PROJECT="$(cd "$(dirname "$0")" && pwd)"
APP="$HOME/Desktop/FanCooler.app"
PYTHON="/usr/local/bin/python3.6"

echo "Building $APP ..."

# ── Create bundle structure ──────────────────────────────────────────────────
mkdir -p "$APP/Contents/MacOS"
mkdir -p "$APP/Contents/Resources"

# ── Launcher script ──────────────────────────────────────────────────────────
cat > "$APP/Contents/MacOS/FanCooler" << LAUNCHER
#!/bin/bash
PROJECT="\$HOME/Desktop/FanCooler"
PYTHON="$PYTHON"
cd "\$PROJECT"
exec "\$PYTHON" "\$PROJECT/main.py"
LAUNCHER
chmod +x "$APP/Contents/MacOS/FanCooler"

# ── Info.plist ───────────────────────────────────────────────────────────────
cat > "$APP/Contents/Info.plist" << 'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>          <string>FanCooler</string>
    <key>CFBundleDisplayName</key>   <string>FanCooler</string>
    <key>CFBundleIdentifier</key>    <string>com.senchabox.fancooler</string>
    <key>CFBundleVersion</key>       <string>1.0</string>
    <key>CFBundleShortVersionString</key> <string>1.0</string>
    <key>CFBundleExecutable</key>    <string>FanCooler</string>
    <key>CFBundlePackageType</key>   <string>APPL</string>
    <key>CFBundleSignature</key>     <string>????</string>
    <key>CFBundleIconFile</key>      <string>AppIcon</string>
    <key>NSHighResolutionCapable</key> <true/>
    <key>NSPrincipalClass</key>      <string>NSApplication</string>
    <key>NSAppleEventsUsageDescription</key>
    <string>FanCooler uses AppleScript to control fan speed.</string>
</dict>
</plist>
PLIST

# ── Icon ─────────────────────────────────────────────────────────────────────
ICONSET="/tmp/FanCooler.iconset"
mkdir -p "$ICONSET"

"$PYTHON" "$PROJECT/make_icon.py"

for pair in "16:icon_16x16" "32:icon_16x16@2x" "32:icon_32x32" \
            "64:icon_32x32@2x" "128:icon_128x128" "256:icon_128x128@2x" \
            "256:icon_256x256" "512:icon_256x256@2x" "512:icon_512x512" \
            "1024:icon_512x512@2x"; do
    sz="${pair%%:*}"
    name="${pair##*:}"
    cp "/tmp/icon_${sz}.png" "$ICONSET/${name}.png"
done

iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/AppIcon.icns"
rm -rf "$ICONSET"

# ── Remove quarantine so Gatekeeper won't block it ───────────────────────────
xattr -cr "$APP"

echo "Done! FanCooler.app is on your Desktop."
echo "You can drag it to the Dock too."
