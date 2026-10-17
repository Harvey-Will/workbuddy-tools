#!/usr/bin/env bash
# Package the macOS portable build (a zip, no installer).
# Counterpart of scripts/build_portable.ps1
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# Stop a previously running portable build if any.
pkill -f 'workbuddy-tools' 2>/dev/null || true
sleep 0.3

# Build the sidecar unless one already exists for this host triple.
# shellcheck source=scripts/_macos_common.sh
source "$(dirname "${BASH_SOURCE[0]}")/_macos_common.sh"
TRIPLE="$(host_triple 2>/dev/null || true)"
if [ -z "$TRIPLE" ] || [ ! -f "src-tauri/binaries/sidecar-$TRIPLE" ]; then
  echo "Building sidecar first..."
  bash scripts/build_sidecar.sh
fi

# Build UI + copy into src-tauri/dist.
npm run ui:build 2>/dev/null || true
node scripts/copy-ui-dist.mjs

npx tauri build --no-bundle

APP_BIN="src-tauri/target/release/workbuddy-tools"
if [ ! -f "$APP_BIN" ]; then
  echo "ERROR: $APP_BIN not built" >&2
  exit 1
fi

VERSION="$(node -p "require('./src-tauri/tauri.conf.json').version")"
PORTABLE="$ROOT/release/WorkBuddyTools-portable-macOS"
rm -rf "$PORTABLE"
mkdir -p "$PORTABLE/Contents/MacOS" "$PORTABLE/Contents/Resources"
cp "$APP_BIN" "$PORTABLE/Contents/MacOS/workbuddy-tools"
chmod +x "$PORTABLE/Contents/MacOS/workbuddy-tools"
cp src-tauri/icons/icon.icns "$PORTABLE/Contents/Resources/icon.icns"

cat > "$PORTABLE/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>WorkBuddy Tools</string>
  <key>CFBundleDisplayName</key><string>WorkBuddy Tools</string>
  <key>CFBundleIdentifier</key><string>com.workbuddy.tools</string>
  <key>CFBundleVersion</key><string>VERSIONVALUE</string>
  <key>CFBundleShortVersionString</key><string>VERSIONVALUE</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>workbuddy-tools</string>
  <key>CFBundleIconFile</key><string>icon.icns</string>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
</dict>
</plist>
PLIST

# Substitute the real version into the generated plist.
sed -i "" "s/VERSIONVALUE/$VERSION/g" "$PORTABLE/Contents/Info.plist"

ZIP="$ROOT/release/WorkBuddyTools-portable-macOS-$VERSION.zip"
rm -f "$ZIP"
(cd release && zip -q -r "WorkBuddyTools-portable-macOS-$VERSION.zip" "WorkBuddyTools-portable-macOS")
echo "PORTABLE_DIR=$PORTABLE"
echo "PORTABLE_ZIP=$ZIP"
du -sh "$PORTABLE" "$ZIP" | awk '{print $1, $2}'
