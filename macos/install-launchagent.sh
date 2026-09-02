#!/usr/bin/env bash
# Install a LaunchAgent so dmswitch starts at login and restarts if it dies.
#
#     ./macos/install-launchagent.sh            # install and load
#     ./macos/install-launchagent.sh --uninstall
#
# The agent runs with --start-hidden, so signing in builds the strip without
# switching you into it or handing the monitor to this machine.

set -euo pipefail

LABEL="com.b2ornot2b.dmswitch"
PLIST="${HOME}/Library/LaunchAgents/${LABEL}.plist"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${REPO}/.venv/bin/python"
APP="${REPO}/build/dmswitch.app"
APP_EXE="${APP}/Contents/MacOS/dmswitch"
LOG_DIR="${HOME}/Library/Logs"

say() { printf '  %s\n' "$*"; }

if [[ "${1:-}" == "--uninstall" ]]; then
    launchctl bootout "gui/$(id -u)/${LABEL}" 2>/dev/null || true
    rm -f "${PLIST}"
    say "removed ${PLIST}"
    exit 0
fi

if [[ ! -x "${PYTHON}" ]]; then
    echo "error: ${PYTHON} not found. Run: uv venv && uv pip install -e '.[dev]'" >&2
    exit 1
fi

# Built fresh each time: the bundle contains absolute paths to this repo.
"${REPO}/macos/make-app-bundle.sh"
SITE_PACKAGES="$("${PYTHON}" -c 'import site; print(site.getsitepackages()[0])')"

mkdir -p "$(dirname "${PLIST}")" "${LOG_DIR}"

cat > "${PLIST}" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${LABEL}</string>

    <key>ProgramArguments</key>
    <array>
        <!-- The bundle's executable, not the bare interpreter: macOS takes
             the displayed app name from the bundle around the running binary,
             so this is what makes it read "dmswitch" instead of "python". -->
        <string>${APP_EXE}</string>
        <!-- -u as well as PYTHONUNBUFFERED: without unbuffered output the log
             file stays empty under launchd and the app looks dead when it is
             actually working. -->
        <string>-u</string>
        <string>-m</string>
        <string>dmswitch</string>
        <string>--start-hidden</string>
        <string>--log-file</string>
        <string>${LOG_DIR}/dmswitch.log</string>
    </array>

    <key>WorkingDirectory</key>
    <string>${REPO}</string>

    <!-- Without this Python block-buffers its output when it is not a
         terminal, so the log file stays empty and the app looks silent even
         when it is working. -->
    <key>EnvironmentVariables</key>
    <dict>
        <key>PYTHONUNBUFFERED</key>
        <string>1</string>
        <!-- Running the interpreter from inside the bundle means it cannot
             find the venv - Python looks for pyvenv.cfg beside the executable
             - so site-packages is supplied explicitly. -->
        <key>PYTHONPATH</key>
        <string>${SITE_PACKAGES}:${REPO}/src</string>
        <!-- launchd's default PATH is /usr/bin:/bin:/usr/sbin:/sbin, which
             excludes Homebrew - so betterdisplaycli resolves from a shell but
             not from here. The app also has its own fallbacks. -->
        <key>PATH</key>
        <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    </dict>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <dict>
        <!-- Restart if it crashes, but not if it exited cleanly: quitting with
             Cmd+Q should stay quit rather than immediately coming back. -->
        <key>SuccessfulExit</key>
        <false/>
    </dict>

    <!-- Do not hot-loop if something is wrong, e.g. missing permissions. -->
    <key>ThrottleInterval</key>
    <integer>30</integer>

    <!-- The app writes its own log via --log-file. Point launchd's streams
         at a separate file so lines are not recorded twice, while still
         catching anything that dies before logging is configured. -->
    <key>StandardOutPath</key>
    <string>${LOG_DIR}/dmswitch.launchd.log</string>
    <key>StandardErrorPath</key>
    <string>${LOG_DIR}/dmswitch.launchd.log</string>
</dict>
</plist>
EOF

say "wrote ${PLIST}"

launchctl bootout "gui/$(id -u)/${LABEL}" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "${PLIST}"
say "loaded ${LABEL}"

sleep 3
if launchctl print "gui/$(id -u)/${LABEL}" >/dev/null 2>&1; then
    say "state: $(launchctl print "gui/$(id -u)/${LABEL}" | awk '/state = /{print $3; exit}')"
fi

cat <<EOF

  Logs: ${LOG_DIR}/dmswitch.log

  The agent runs from a bundle so macOS shows it as "dmswitch". Its executable
  is a symlink to the venv interpreter, and TCC keys its grants to the
  underlying binary, so an existing grant for:

      ${PYTHON}

  normally continues to apply. If the log says "could not create event tap",
  grant Accessibility and Input Monitoring to:

      ${APP}

  under System Settings > Privacy & Security.
EOF
