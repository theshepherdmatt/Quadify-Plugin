#!/bin/bash
set -e

cd "$(dirname "$0")"
LOG_FILE="install.log"
rm -f "$LOG_FILE"
log() { echo "[Quadify Install] $1" | tee -a "$LOG_FILE"; }

log "Installing system dependencies..."
apt-get update
apt-get install -y python3 python3-pip python3-venv \
  libjpeg-dev zlib1g-dev libfreetype6-dev \
  i2c-tools python3-smbus libgirepository1.0-dev \
  pkg-config libcairo2-dev libffi-dev build-essential \
  libxml2-dev libxslt1-dev libssl-dev lirc lsof \
  python3-gi python3-cairo gir1.2-gtk-3.0

# --- Optionally clean up broken Python packages (if needed) ---
log "Cleaning up Python packaging issues..."
pip3 uninstall -y importlib-metadata setuptools python-socketio socketio socketIO-client >/dev/null 2>&1 || true

# -- This block is optional and potentially risky, only if you're sure --
# rm -rf /usr/local/lib/python3.7/dist-packages/importlib_metadata*
# rm -rf /usr/local/lib/python3.7/dist-packages/setuptools*
# rm -rf /usr/local/lib/python3.7/dist-packages/socketio*
# rm -rf /usr/local/lib/python3.7/dist-packages/python_socketio*
# rm -rf /usr/local/lib/python3.7/dist-packages/socketIO_client*

log "Upgrading pip and setuptools..."
python3 -m pip install --upgrade pip setuptools importlib-metadata

log "Installing Python dependencies from requirements.txt..."
python3 -m pip install --upgrade --ignore-installed -r ./quadifyapp/requirements.txt

# <--- ADD THIS BLOCK FOR NODE.JS DEPENDENCIES --->
log "Installing Node.js dependencies..."
if [ -f package.json ]; then
  npm install --production --silent
  log "Node.js dependencies installed."
else
  log "Warning: package.json not found, skipping npm install."
fi
# <--- END ADDITION --->

log "Enabling I2C/SPI overlays in /boot/userconfig.txt..."
CONFIG_FILE="/boot/userconfig.txt"
touch "$CONFIG_FILE"
grep -qxF 'dtparam=spi=on' "$CONFIG_FILE" || echo 'dtparam=spi=on' >> "$CONFIG_FILE"
grep -qxF 'dtparam=i2c_arm=on' "$CONFIG_FILE" || echo 'dtparam=i2c_arm=on' >> "$CONFIG_FILE"
modprobe i2c-dev || true
modprobe spi-bcm2835 || true

# ---- Service setup ----
log "Setting up systemd services..."
SERVICES=("quadify.service" "ir_listener.service" "early_led8.service" "cava.service")
for svc in "${SERVICES[@]}"; do
  if [ -f "quadifyapp/service/$svc" ]; then
    cp "quadifyapp/service/$svc" "/etc/systemd/system/$svc"
    chmod 644 "/etc/systemd/system/$svc"
    systemctl daemon-reload
    systemctl enable "$svc"
    systemctl restart "$svc" || log "$svc could not be started (may depend on other conditions)"
  else
    log "$svc not found, skipping..."
  fi
done

log "Setting permissions for plugin folder..."
chown -R volumio:volumio .
chmod -R 755 .

# ---- Dev-only: Sanity check for Python packaging ----
python3 -c "import importlib_metadata, setuptools, socketio; print('Packaging OK:', hasattr(importlib_metadata, 'MetadataPathFinder'), setuptools.__version__, hasattr(socketio, 'Client'))" || { echo 'Packaging is still broken!'; exit 1; }

log "Quadify installation complete. Configure features via plugin UI."

