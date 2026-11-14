#!/bin/sh
# 编译 Hub.app 并安装到 ~/Applications（桌面放一个替身）。用法：sh app/build.sh
set -e
cd "$(dirname "$0")"
B=$(mktemp -d)
APP="$B/Hub.app"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
swiftc -O -o "$APP/Contents/MacOS/Hub" HubApp.swift -framework Cocoa -framework WebKit
swiftc -o "$B/mkicon" MakeIcon.swift -framework Cocoa
"$B/mkicon" "$B/icon.png"
mkdir "$B/Hub.iconset"
for s in 16 32 128 256 512; do
  sips -z $s $s "$B/icon.png" --out "$B/Hub.iconset/icon_${s}x${s}.png" >/dev/null
  d=$((s * 2)); sips -z $d $d "$B/icon.png" --out "$B/Hub.iconset/icon_${s}x${s}@2x.png" >/dev/null
done
iconutil -c icns "$B/Hub.iconset" -o "$APP/Contents/Resources/Hub.icns"
cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleName</key><string>Hub</string>
<key>CFBundleDisplayName</key><string>Hub</string>
<key>CFBundleIdentifier</key><string>local.agent-hub.panel</string>
<key>CFBundleExecutable</key><string>Hub</string>
<key>CFBundleIconFile</key><string>Hub</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleShortVersionString</key><string>1.0</string>
<key>CFBundleVersion</key><string>2</string>
<key>LSMinimumSystemVersion</key><string>12.0</string>
<key>NSHighResolutionCapable</key><true/>
<key>NSAppTransportSecurity</key><dict><key>NSAllowsLocalNetworking</key><true/></dict>
</dict></plist>
PLIST
codesign --force -s - "$APP" >/dev/null 2>&1 || true
mkdir -p "$HOME/Applications"
rm -rf "$HOME/Applications/Hub.app"
cp -R "$APP" "$HOME/Applications/Hub.app"
ln -sfn "$HOME/Applications/Hub.app" "$HOME/Desktop/Hub.app"
rm -rf "$B"
echo "已安装：$HOME/Applications/Hub.app"
