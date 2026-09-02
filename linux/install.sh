#!/usr/bin/env bash
# Install the this machine side of dmswitch: the receiver and the systemd user
# units that keep it and ydotoold running across reboots.
#
# Run on this machine, as the user whose desktop session is being shared:
#
#     ./install.sh
#
# No root required. /dev/uinput is root:input 0660 via the udev rule shipped
# with the ydotool package, and this user needs to be in the `input` group.

set -euo pipefail

BIN_DIR="${HOME}/.local/bin"
UNIT_DIR="${HOME}/.config/systemd/user"
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# The output name of the shared monitor, as Hyprland reports it. Getting this
# wrong is the most likely first failure, so it is a first-class argument.
MONITOR="${DMSWITCH_MONITOR:-${1:-}}"
PORT="${DMSWITCH_PORT:-24810}"

say() { printf '  %s\n' "$*"; }

echo "checking prerequisites"

if ! command -v ydotoold >/dev/null; then
    echo "error: ydotoold not found. Install it first: sudo pacman -S ydotool" >&2
    exit 1
fi
say "ydotoold: $(command -v ydotoold)"

for tool in hyprctl grim; do
    if ! command -v "${tool}" >/dev/null; then
        echo "error: ${tool} not found. hyprctl is required; grim is needed for" >&2
        echo "       the Space thumbnails. Install with: sudo pacman -S ${tool}" >&2
        exit 1
    fi
    say "${tool}: $(command -v ${tool})"
done

# Over SSH there is no compositor in the environment, and more than one
# Hyprland may be running, so ask each instance in turn rather than relying on
# HYPRLAND_INSTANCE_SIGNATURE being set.
list_monitors() {
    local runtime="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
    local sig names
    for sig in "${runtime}"/hypr/*/; do
        [[ -d "${sig}" ]] || continue
        names="$(hyprctl -i "$(basename "${sig}")" monitors -j 2>/dev/null \
            | python3 -c 'import json,sys
try: print(" ".join(m["name"] for m in json.load(sys.stdin)))
except Exception: pass' 2>/dev/null)"
        if [[ -n "${names}" ]]; then
            echo "${names}"
            return 0
        fi
    done
    return 1
}

if [[ -z "${MONITOR}" ]]; then
    AVAILABLE="$(list_monitors || true)"
    # shellcheck disable=SC2086
    set -- ${AVAILABLE}
    if [[ $# -eq 1 ]]; then
        MONITOR="$1"
        say "monitor: ${MONITOR} (the only one; pass an argument to override)"
    else
        echo "error: could not pick the shared monitor automatically." >&2
        if [[ $# -gt 1 ]]; then
            echo "       Several are connected: ${AVAILABLE}" >&2
        else
            echo "       No running Hyprland found. Run this from the desktop session." >&2
        fi
        echo "       Pass the output name of the shared monitor, e.g.:" >&2
        echo "           ./install.sh HDMI-A-1" >&2
        exit 1
    fi
else
    say "monitor: ${MONITOR}"
fi

if ! id -nG | tr ' ' '\n' | grep -qx input; then
    echo "error: $(id -un) is not in the 'input' group, so ydotoold cannot open" >&2
    echo "       /dev/uinput. Fix with: sudo usermod -aG input $(id -un)" >&2
    echo "       then log out and back in." >&2
    exit 1
fi
say "input group: yes"

if [[ ! -r /dev/uinput || ! -w /dev/uinput ]]; then
    echo "warning: /dev/uinput is not readable and writable by this user." >&2
    echo "         Currently: $(ls -l /dev/uinput)" >&2
    echo "         The udev rule from the ydotool package sets root:input 0660," >&2
    echo "         but it only applies once the uinput module is (re)loaded, so a" >&2
    echo "         reboot may be needed if the package was installed recently." >&2
fi

echo "installing"
mkdir -p "${BIN_DIR}" "${UNIT_DIR}"
install -m 0755 "${SOURCE_DIR}/dmswitch_receiver.py" "${BIN_DIR}/dmswitch_receiver.py"
say "receiver -> ${BIN_DIR}/dmswitch_receiver.py"
install -m 0644 "${SOURCE_DIR}/systemd/ydotoold.service" "${UNIT_DIR}/ydotoold.service"
sed -e "s|@MONITOR@|${MONITOR}|g" -e "s|@PORT@|${PORT}|g" \
    "${SOURCE_DIR}/systemd/dmswitch-receiver.service" \
    > "${UNIT_DIR}/dmswitch-receiver.service"
say "units    -> ${UNIT_DIR}/"

echo "enabling"
systemctl --user daemon-reload
systemctl --user enable --now ydotoold.service
systemctl --user enable --now dmswitch-receiver.service

sleep 2
echo "status"
for unit in ydotoold dmswitch-receiver; do
    say "${unit}: $(systemctl --user is-enabled "${unit}.service" 2>&1) / $(systemctl --user is-active "${unit}.service" 2>&1)"
done

if ! loginctl show-user "$(id -un)" -p Linger 2>/dev/null | grep -q Linger=yes; then
    echo
    say "note: lingering is off, so these start with your graphical session"
    say "      rather than at boot. That is what you want here - the receiver"
    say "      needs a running compositor to talk to. Enable it only if you"
    say "      want them up before login: loginctl enable-linger $(id -un)"
fi
