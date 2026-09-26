#!/bin/sh
# Install the Home Assistant dashboard on a Raspberry Pi Zero 2W
# running Raspberry Pi OS Lite (Bookworm or later).
#
#   sudo ./install.sh            # dashboard server + full-screen kiosk
#   sudo ./install.sh --no-kiosk # dashboard server only
set -eu

KIOSK=1
[ "${1:-}" = "--no-kiosk" ] && KIOSK=0

if [ "$(id -u)" -ne 0 ]; then
  echo "run with sudo" >&2
  exit 1
fi

# The service runs as the (non-root) user who invoked sudo, or HA_DASH_USER.
RUN_USER="${HA_DASH_USER:-${SUDO_USER:-}}"
if [ -z "$RUN_USER" ] || [ "$RUN_USER" = "root" ]; then
  echo "run as your normal user via sudo, or set HA_DASH_USER=<user>" >&2
  exit 1
fi
if ! id "$RUN_USER" >/dev/null 2>&1; then
  echo "user '$RUN_USER' does not exist" >&2
  exit 1
fi
SRC_DIR="$(cd "$(dirname "$0")" && pwd)"
INSTALL_DIR="/opt/ha-dashboard"

echo "==> Installing to $INSTALL_DIR (service user: $RUN_USER)"
mkdir -p "$INSTALL_DIR"
cp -r "$SRC_DIR/server.py" "$SRC_DIR/kiosk.sh" "$SRC_DIR/static" "$INSTALL_DIR/"
chmod +x "$INSTALL_DIR/server.py" "$INSTALL_DIR/kiosk.sh"

if [ ! -f "$INSTALL_DIR/config.json" ]; then
  cp "$SRC_DIR/config.example.json" "$INSTALL_DIR/config.json"
  echo "==> Created $INSTALL_DIR/config.json - edit it with your HA URL, token and tiles"
fi
# The config holds an access token: readable by the service user only.
chown "$RUN_USER" "$INSTALL_DIR/config.json"
chmod 600 "$INSTALL_DIR/config.json"

install_unit() {
  sed -e "s|@USER@|$RUN_USER|g" -e "s|@INSTALL_DIR@|$INSTALL_DIR|g" \
    "$SRC_DIR/systemd/$1" > "/etc/systemd/system/$1"
}

install_unit ha-dashboard.service
systemctl daemon-reload
systemctl enable ha-dashboard.service
# Restart (not just start) so a re-run picks up the newly copied files.
systemctl restart ha-dashboard.service

if [ "$KIOSK" -eq 1 ]; then
  echo "==> Installing kiosk packages (cage, chromium)"
  apt-get update
  apt-get install -y --no-install-recommends cage
  apt-get install -y --no-install-recommends chromium || \
    apt-get install -y --no-install-recommends chromium-browser
  # Give the user access to the display, input and GPU devices.
  usermod -aG video,render,input,tty "$RUN_USER"

  install_unit ha-kiosk.service
  systemctl daemon-reload
  systemctl set-default graphical.target
  systemctl disable getty@tty1.service || true
  systemctl enable ha-kiosk.service
  echo "==> Kiosk enabled on tty1 - reboot to start it"
fi

echo "==> Done. Dashboard: http://127.0.0.1:8080/ (logs: journalctl -u ha-dashboard -f)"
