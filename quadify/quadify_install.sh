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
  libxml2-dev libxslt1-dev libssl-dev lirc lsof

CONFIG_FILE="/boot/userconfig.txt"
touch "$CONFIG_FILE"
grep -qxF 'dtparam=spi=on' "$CONFIG_FILE" || echo 'dtparam=spi=on' >> "$CONFIG_FILE"
grep -qxF 'dtparam=i2c_arm=on' "$CONFIG_FILE" || echo 'dtparam=i2c_arm=on' >> "$CONFIG_FILE"
modprobe i2c-dev || true
modprobe spi-bcm2835 || true

log "Upgrading pip..."
python3 -m pip install --upgrade pip setuptools wheel
log "Installing Python dependencies..."
python3 -m pip install --upgrade --ignore-installed -r requirements.txt

log "Setting up systemd services..."
SERVICES=("quadify.service" "ir_listener.service" "early_led8.service" "cava.service")
for svc in "${SERVICES[@]}"; do
  if [ -f "service/$svc" ]; then
    cp "service/$svc" "/etc/systemd/system/$svc"
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

log "Quadify installation complete. Configure buttons, IR, CAVA via plugin UI."
