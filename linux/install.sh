#!/usr/bin/env bash
# Install the b2omarchy side of dmswitch: the receiver and the systemd user
# units that keep it and ydotoold running across reboots.
#
# Run on b2omarchy, as the user whose desktop session is being shared:
#
#     ./install.sh
#
# No root required. /dev/uinput is root:input 0660 via the udev rule shipped
# with the ydotool package, and this user needs to be in the `input` group.

set -euo pipefail

BIN_DIR="${HOME}/.local/bin"
UNIT_DIR="${HOME}/.config/systemd/user"
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

say() { printf '  %s\n' "$*"; }

echo "checking prerequisites"

if ! command -v ydotoold >/dev/null; then
    echo "error: ydotoold not found. Install it first: sudo pacman -S ydotool" >&2
    exit 1
fi
say "ydotoold: $(command -v ydotoold)"

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
install -m 0644 "${SOURCE_DIR}/systemd/dmswitch-receiver.service" "${UNIT_DIR}/dmswitch-receiver.service"
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
