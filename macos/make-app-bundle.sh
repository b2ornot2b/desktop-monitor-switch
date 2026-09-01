#!/usr/bin/env bash
# Build a minimal .app bundle so macOS shows "dmswitch" rather than "python".
#
#     ./macos/make-app-bundle.sh        # writes build/dmswitch.app
#
# The name macOS displays - in Mission Control, the menu bar, Force Quit -
# comes from LaunchServices, which reads it from the bundle containing the
# running executable. Patching CFBundleName at runtime does nothing, before or
# after NSApplication is created; only a real bundle works.
#
# The trick is that Contents/MacOS/dmswitch is a **symlink to the venv's
# python**, so the executable path lies inside the bundle and LaunchServices
# attributes the process to it. Python then cannot find the venv - it looks for
# pyvenv.cfg beside the executable - so PYTHONPATH supplies site-packages
# instead. The launcher script below and the LaunchAgent both set it.

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PYTHON="${REPO}/.venv/bin/python"
APP="${REPO}/build/dmswitch.app"

if [[ ! -x "${VENV_PYTHON}" ]]; then
    echo "error: ${VENV_PYTHON} not found. Run: uv venv && uv pip install -e '.[dev]'" >&2
    exit 1
fi

SITE_PACKAGES="$("${VENV_PYTHON}" -c 'import site; print(site.getsitepackages()[0])')"
VERSION="$("${VENV_PYTHON}" -c 'import dmswitch; print(dmswitch.__version__)' 2>/dev/null || echo 0.1.0)"

rm -rf "${APP}"
mkdir -p "${APP}/Contents/MacOS" "${APP}/Contents/Resources"

cat > "${APP}/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>
    <string>dmswitch</string>
    <key>CFBundleDisplayName</key>
    <string>dmswitch</string>
    <key>CFBundleIdentifier</key>
    <string>com.b2ornot2b.dmswitch</string>
    <key>CFBundleExecutable</key>
    <string>dmswitch</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleShortVersionString</key>
    <string>${VERSION}</string>
    <key>CFBundleVersion</key>
    <string>${VERSION}</string>
    <key>NSHighResolutionCapable</key>
    <true/>
    <key>LSMinimumSystemVersion</key>
    <string>13.0</string>
</dict>
</plist>
EOF

# Symlink rather than copy: the executable must live inside the bundle for
# LaunchServices to attribute the process to it, and a copied interpreter
# would lose track of its own framework.
ln -sf "${VENV_PYTHON}" "${APP}/Contents/MacOS/dmswitch"

# A convenience launcher for running it by hand, with the environment the
# bundle needs. The LaunchAgent sets the same variables itself.
cat > "${APP}/Contents/MacOS/run" <<EOF
#!/bin/sh
export PYTHONPATH="${SITE_PACKAGES}:${REPO}/src"
export PYTHONUNBUFFERED=1
exec "${APP}/Contents/MacOS/dmswitch" -u -m dmswitch "\$@"
EOF
chmod +x "${APP}/Contents/MacOS/run"

printf '  built %s\n' "${APP}"
printf '  name macOS will show: %s\n' \
    "$(PYTHONPATH="${SITE_PACKAGES}:${REPO}/src" "${APP}/Contents/MacOS/dmswitch" -c '
import AppKit
AppKit.NSApplication.sharedApplication().setActivationPolicy_(
    AppKit.NSApplicationActivationPolicyRegular)
print(AppKit.NSRunningApplication.currentApplication().localizedName())' 2>/dev/null || echo '?')"
