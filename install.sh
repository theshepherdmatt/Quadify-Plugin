#!/bin/bash
# Quadify – plugin installer
set -euo pipefail

cd "$(dirname "$0")"
LOG_FILE="install.log"
rm -f "$LOG_FILE"

log() { echo "[Quadify Install] $1" | tee -a "$LOG_FILE"; }

# 1. System prerequisites
log "Installing system dependencies …"
apt-get update
apt-get install -y \
  python3 python3-pip python3-venv \
  libjpeg-dev zlib1g-dev libfreetype6-dev \
  i2c-tools python3-smbus \
  libgirepository1.0-dev pkg-config libcairo2-dev python3-gi python3-cairo gir1.2-gtk-3.0 \
  build-essential libffi-dev libxml2-dev libxslt1-dev libssl-dev \
  lirc lsof

# 2. Clean up any broken global Python packages
log "Removing conflicting Python packages …"
pip3 uninstall -y importlib-metadata setuptools python-socketio socketio socketIO-client >/dev/null 2>&1 || true
PY36_SITEPKG=$(python3 - <<'PY' ; import site, pathlib ; print(pathlib.Path(next(p for p in site.getsitepackages() if 'dist-packages' in p))) ; PY)
rm -rf "${PY36_SITEPKG}"/{importlib_metadata*,setuptools*,socketio*,python_socketio*,socketIO_client*}

log "Upgrading pip / setuptools / importlib-metadata …"
python3 -m pip install --upgrade pip setuptools importlib-metadata

# 3. Install Node.js plugin dependencies (v-conf, js-yaml, fs-extra, kew)
log "Installing Node.js dependencies …"
npm install --production --silent

# 4. Install plugin-specific Python requirements (global, not venv)
log "Installing Python dependencies from requirements.txt …"
python3 -m pip install --upgrade --ignore-installed -r ./quadifyapp/requirements.txt

# 5. Enable I2C / SPI overlays
log "Enabling I2C & SPI in /boot/userconfig.txt …"
CONFIG_FILE="/boot/userconfig.txt"
touch "$CONFIG_FILE"
grep -qxF 'dtparam=spi=on'     "$CONFIG_FILE" || echo 'dtparam=spi=on'     >> "$CONFIG_FILE"
grep -qxF 'dtparam=i2c_arm=on' "$CONFIG_FILE" || echo 'dtparam=i2c_arm=on' >> "$CONFIG_FILE"
modprobe i2c-dev || true
modprobe spi-bcm2835 || true

if [ ! -e /dev/spidev0.0 ]; then
  log "SPI device not present yet – a reboot will be required before Quadify works."
  START_SERVICE=0
else
  START_SERVICE=1
fi

# 6. Install / enable the systemd service
log "Setting up systemd service …"
SERVICE_SRC="quadifyapp/service/quadify.service"
SERVICE_DST="/etc/systemd/system/quadify.service"

if [ -f "$SERVICE_SRC" ]; then
  cp "$SERVICE_SRC" "$SERVICE_DST"
  systemctl daemon-reload
  systemctl enable quadify.service
  if [ "$START_SERVICE" -eq 1 ]; then
    systemctl restart quadify.service
  else
    log "Not starting service now (reboot required)."
  fi
else
  log "Warning: $SERVICE_SRC missing – skipping systemd setup."
fi

# 7. Permissions
log "Fixing ownership & permissions …"
chown -R volumio:volumio .
chmod -R 755 .

# 8. Sanity check (dev-time helper)
python3 - <<'PY' || { log 'Packaging is still broken!'; exit 1; }
import importlib_metadata, setuptools, socketio, sys
print('Packaging OK →', setuptools.__version__)
PY

log "Quadify base installation complete. Buttons / IR / rotary can now be enabled from plugin settings."
