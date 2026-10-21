#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
APP_NAME="Roach Detector"
DIST="$ROOT/dist"
APP="$DIST/${APP_NAME}.app"
CONTENTS="$APP/Contents"
RES="$CONTENTS/Resources"
MACOS="$CONTENTS/MacOS"
ICON_SRC="$ROOT/assets/icon.png"

rm -rf "$DIST"
mkdir -p "$MACOS" "$RES/assets" "$RES/fixtures" "$RES/sample-output" "$RES/settlement_watch"

cp "$ROOT/settlement_watch/"*.py "$RES/settlement_watch/"
cp "$ROOT/fixtures/demo_dockets.json" "$RES/fixtures/"
cp "$ROOT/watchlist.example.csv" "$RES/"
cp -R "$ROOT/sample-output/." "$RES/sample-output/"
if [[ -f "$ICON_SRC" ]]; then
  cp "$ICON_SRC" "$RES/assets/icon.png"
fi
if [[ -f "$ROOT/assets/AppIcon.icns" ]]; then
  cp "$ROOT/assets/AppIcon.icns" "$RES/AppIcon.icns"
fi

cat > "$CONTENTS/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key>
  <string>Roach Detector</string>
  <key>CFBundleDisplayName</key>
  <string>Roach Detector</string>
  <key>CFBundleIdentifier</key>
  <string>local.jamesmurphy.roach-detector</string>
  <key>CFBundleVersion</key>
  <string>1.1.0</string>
  <key>CFBundleShortVersionString</key>
  <string>1.1.0</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>CFBundleExecutable</key>
  <string>Roach Detector</string>
  <key>CFBundleIconFile</key>
  <string>AppIcon</string>
  <key>LSMinimumSystemVersion</key>
  <string>13.0</string>
  <key>NSHighResolutionCapable</key>
  <true/>
  <key>LSUIElement</key>
  <false/>
</dict>
</plist>
PLIST

cat > "$MACOS/Roach Detector" <<'LAUNCH'
#!/bin/bash
set -euo pipefail
RES="$(cd "$(dirname "$0")/../Resources" && pwd)"
cd "$RES"
export PYTHONPATH="$RES${PYTHONPATH:+:$PYTHONPATH}"
if [[ -x /Library/Frameworks/Python.framework/Versions/3.14/bin/python3 ]]; then
  exec /Library/Frameworks/Python.framework/Versions/3.14/bin/python3 -m settlement_watch
fi
exec /usr/bin/env python3 -m settlement_watch
LAUNCH
chmod +x "$MACOS/Roach Detector"

echo "Built $APP"
