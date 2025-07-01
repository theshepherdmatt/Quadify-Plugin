#!/bin/bash
set -e

# Always run from the directory this script is in
cd "$(dirname "$0")"

LOG_FILE="install.log"
rm -f "$LOG_FILE"

log() { echo "[Quadify Install] $1" | tee -a "$LOG_FILE"; }

# Optional hardware (leave off at install, enable in plugin UI)
BUTTONSLEDS_ENABLED=false
IR_REMOTE_SUPPORT=false

# 1. Install system dependencies
log "Installing system dependencies..."
apt-get update
apt-get install -y python3 python3-pip libjpeg-dev zlib1g-dev \
  libfreetype6-dev i2c-tools python3-smbus libgirepository1.0-dev \
  pkg-config libcairo2-dev libffi-dev build-essential \
  libxml2-dev libxslt1-dev libssl-dev lirc lsof

# 2. Enable I2C/SPI (default ON)
CONFIG_FILE="/boot/userconfig.txt"
touch "$CONFIG_FILE"
grep -qxF 'dtparam=spi=on' "$CONFIG_FILE" || echo 'dtparam=spi=on' >> "$CONFIG_FILE"
grep -qxF 'dtparam=i2c_arm=on' "$CONFIG_FILE" || echo 'dtparam=i2c_arm=on' >> "$CONFIG_FILE"
modprobe i2c-dev || true
modprobe spi-bcm2835 || true

# 3. Upgrade pip, install Python deps
log "Upgrading pip..."
python3 -m pip install --upgrade pip setuptools wheel
log "Installing Python dependencies..."
python3 -m pip install --upgrade --ignore-installed -r requirements.txt

# 4. Set up Quadify systemd service (using correct plugin path)
log "Setting up systemd service for Quadify..."
if [ -f service/quadify.service ]; then
  cp service/quadify.service /etc/systemd/system/quadify.service
  systemctl daemon-reload
  systemctl enable quadify.service
  systemctl restart quadify.service
else
  log "No service/quadify.service found! Skipping systemd setup."
fi

# 5. Set permissions for plugin folder
chown -R volumio:volumio .
chmod -R 755 .

log "Quadify base installation complete. (Buttons/IR/rotary can be enabled via plugin settings/UI.)"

