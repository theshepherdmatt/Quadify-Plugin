#!/bin/bash
set -e

cd "$(dirname "$0")"

LOG_FILE="install.log"
rm -f "$LOG_FILE"

log() { echo "[Quadify Install] $1" | tee -a "$LOG_FILE"; }

log "Installing system dependencies..."
apt-get update
apt-get install -y python3 python3-pip libjpeg-dev zlib1g-dev \
  libfreetype6-dev i2c-tools python3-smbus libgirepository1.0-dev \
  pkg-config libcairo2-dev libffi-dev build-essential \
  libxml2-dev libxslt1-dev libssl-dev lirc lsof \
  python3-gi python3-cairo gir1.2-gtk-3.0

# ---- Nuke broken Python package installs before installing requirements ----
log "Cleaning up Python packaging issues (importlib-metadata, setuptools)..."
pip3 uninstall -y importlib-metadata setuptools python-socketio socketio socketIO-client >/dev/null 2>&1 || true
rm -rf /usr/local/lib/python3.7/dist-packages/importlib_metadata*
rm -rf /usr/local/lib/python3.7/dist-packages/setuptools*
rm -rf /usr/local/lib/python3.7/dist-packages/socketio*
rm -rf /usr/local/lib/python3.7/dist-packages/python_socketio*
rm -rf /usr/local/lib/python3.7/dist-packages/socketIO_client*

log "Upgrading pip and rebuilding setuptools/importlib-metadata..."
python3 -m pip install --upgrade pip
python3 -m pip install --upgrade setuptools importlib-metadata

log "Installing Python dependencies from requirements.txt..."
python3 -m pip install --upgrade --ignore-installed -r ./quadify/requirements.txt

# ---- Usual plugin install steps ----
log "Enabling I2C/SPI in /boot/userconfig.txt..."
CONFIG_FILE="/boot/userconfig.txt"
touch "$CONFIG_FILE"
grep -qxF 'dtparam=spi=on' "$CONFIG_FILE" || echo 'dtparam=spi=on' >> "$CONFIG_FILE"
grep -qxF 'dtparam=i2c_arm=on' "$CONFIG_FILE" || echo 'dtparam=i2c_arm=on' >> "$CONFIG_FILE"
modprobe i2c-dev || true
modprobe spi-bcm2835 || true

log "Setting up systemd service for Quadify..."
if [ -f quadify/service/quadify.service ]; then
  cp quadify/service/quadify.service /etc/systemd/system/quadify.service
  systemctl daemon-reload
  systemctl enable quadify.service
  systemctl restart quadify.service
else
  log "No quadify/service/quadify.service found! Skipping systemd setup."
fi

log "Setting permissions for plugin folder..."
chown -R volumio:volumio .
chmod -R 755 .

# ---- Sanity check for packaging (optional, dev only) ----
python3 -c "import importlib_metadata, setuptools, socketio; print('Packaging OK:', hasattr(importlib_metadata, 'MetadataPathFinder'), setuptools.__version__, hasattr(socketio, 'Client'))" || { echo 'Packaging is still broken!'; exit 1; }

log "Quadify base installation complete. (Buttons/IR/rotary can be enabled via plugin settings/UI.)"
