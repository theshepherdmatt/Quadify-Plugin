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
  libfftw3-dev libasound2-dev libncursesw5-dev libpulse-dev \
  libtool automake autoconf gcc make pkg-config libiniparser-dev

log "Upgrading pip..."
python3 -m pip install --upgrade pip setuptools wheel

log "Installing Python dependencies..."
python3 -m pip install --upgrade --ignore-installed -r requirements.txt

log "Enabling I2C/SPI in /boot/userconfig.txt..."
CONFIG_FILE="/boot/userconfig.txt"
touch "$CONFIG_FILE"
grep -qxF 'dtparam=spi=on' "$CONFIG_FILE" || echo 'dtparam=spi=on' >> "$CONFIG_FILE"
grep -qxF 'dtparam=i2c_arm=on' "$CONFIG_FILE" || echo 'dtparam=i2c_arm=on' >> "$CONFIG_FILE"
modprobe i2c-dev || true
modprobe spi-bcm2835 || true

log "Setting up systemd service for Quadify..."
if [ -f service/quadify.service ]; then
  cp service/quadify.service /etc/systemd/system/quadify.service
  systemctl daemon-reload
  systemctl enable quadify.service
  systemctl restart quadify.service
else
  log "No quadify.service found!"
fi

log "Installing early LED service..."
if [ -f service/early_led8.service ]; then
  cp service/early_led8.service /etc/systemd/system/
  chmod +x scripts/early_led8.py
  systemctl enable early_led8.service
  systemctl start early_led8.service
else
  log "No early_led8.service found!"
fi

log "Installing IR listener service..."
if [ -f service/ir_listener.service ]; then
  cp service/ir_listener.service /etc/systemd/system/
  systemctl enable ir_listener.service
  systemctl start ir_listener.service
else
  log "No ir_listener.service found!"
fi

log "Installing CAVA..."
CAVA_DIR="/home/volumio/cava"
if [ ! -x /usr/local/bin/cava ]; then
  git clone https://github.com/theshepherdmatt/cava.git "$CAVA_DIR"
  cd "$CAVA_DIR"
  ./autogen.sh
  ./configure
  make
  make install
else
  log "CAVA already installed."
fi

log "Setting up CAVA systemd service..."
if [ -f service/cava.service ]; then
  cp service/cava.service /etc/systemd/system/
  systemctl enable cava.service
else
  log "No cava.service found!"
fi

log "Setting permissions..."
chown -R volumio:volumio .
chmod -R 755 .

log "Installation complete. Use plugin UI to toggle CAVA, IR, or Buttons/LEDs."
