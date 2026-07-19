#!/usr/bin/env bash
# Idempotent installer for the visio-tv listener. Run on the Pi itself,
# after this pi/ directory has been scp'd to /home/julienne/visio-tv/.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="$SCRIPT_DIR"
ENV_FILE="$INSTALL_DIR/.env"
VENV_DIR="$INSTALL_DIR/venv"
AUTOSTART_FILE="$HOME/.config/labwc/autostart"
AUTOSTART_MARKER="visio-tv-listener.service"
USER_SYSTEMD_DIR="$HOME/.config/systemd/user"

echo "==> Checking prerequisites"
if [ ! -f "$ENV_FILE" ]; then
  echo "ERROR: $ENV_FILE not found." >&2
  echo "Copy $INSTALL_DIR/.env.example to $ENV_FILE and fill in the real" >&2
  echo "SUPABASE_URL / SUPABASE_ANON_KEY before running this installer." >&2
  exit 1
fi
command -v firefox >/dev/null || { echo "ERROR: firefox not found on PATH" >&2; exit 1; }
command -v python3 >/dev/null || { echo "ERROR: python3 not found on PATH" >&2; exit 1; }

echo "==> Setting up Python virtualenv"
if [ ! -d "$VENV_DIR" ]; then
  python3 -m venv "$VENV_DIR"
fi
"$VENV_DIR/bin/pip" install --upgrade pip
"$VENV_DIR/bin/pip" install -r "$INSTALL_DIR/listener/requirements.txt"

echo "==> Installing systemd --user unit"
mkdir -p "$USER_SYSTEMD_DIR"
cp "$INSTALL_DIR/systemd/visio-tv-listener.service" "$USER_SYSTEMD_DIR/visio-tv-listener.service"

echo "==> Setting up Firefox kiosk profile"
FIREFOX_PROFILE_DIR="${FIREFOX_PROFILE_DIR:-$HOME/.config/visio-tv-ff}"
mkdir -p "$FIREFOX_PROFILE_DIR"
cp "$INSTALL_DIR/firefox/user.js" "$FIREFOX_PROFILE_DIR/user.js"

echo "==> Installing Firefox enterprise policy (camera/mic allow for meet.jit.si)"
if sudo -n true 2>/dev/null; then
  sudo mkdir -p /etc/firefox/policies
  sudo cp "$INSTALL_DIR/policies/firefox-policies.json" /etc/firefox/policies/policies.json
else
  if [ -f /etc/firefox/policies/policies.json ]; then
    echo "policies.json already present, and sudo needs a password here — skipping"
  else
    echo "WARNING: could not install /etc/firefox/policies/policies.json (sudo needs a password)."
    echo "Run manually: sudo mkdir -p /etc/firefox/policies && sudo cp $INSTALL_DIR/policies/firefox-policies.json /etc/firefox/policies/policies.json"
  fi
fi

echo "==> Wiring labwc autostart"
mkdir -p "$(dirname "$AUTOSTART_FILE")"
touch "$AUTOSTART_FILE"
chmod +x "$AUTOSTART_FILE"
if ! grep -qF "$AUTOSTART_MARKER" "$AUTOSTART_FILE"; then
  cat "$INSTALL_DIR/labwc/autostart.snippet" >> "$AUTOSTART_FILE"
  echo "Appended autostart snippet to $AUTOSTART_FILE"
else
  echo "Autostart snippet already present, skipping"
fi

echo "==> Enabling linger so the user systemd manager runs without an active login"
sudo loginctl enable-linger "$USER"

echo "==> Disabling screen blanking"
sudo raspi-config nonint do_blanking 1 || echo "WARNING: could not set do_blanking, check screen blanking manually (see docs/RUNBOOK.md)"

echo "==> Reloading systemd --user"
systemctl --user daemon-reload

cat <<EOF

==> Install complete.

Next steps:
  1. Reboot (or log out/in) so labwc's autostart picks up the new service:
       sudo reboot
  2. After it's back up, check the service is active:
       systemctl --user status visio-tv-listener.service
  3. Watch logs:
       journalctl --user -u visio-tv-listener.service -f
EOF
