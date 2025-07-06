#!/bin/bash
set -e

cd "$(dirname "$0")"
LOG_FILE="install.log"
rm -f "$LOG_FILE"

log() { echo "[Quadify Install] $1" | tee -a "$LOG_FILE"; }
log_progress() { log "$1"; }      # For legacy compatibility
log_message() { log "$2"; }       # For legacy compatibility with type param
show_random_tip() { :; }          # No-op (replace if you want tips!)

check_cava_installed() {
  command -v cava >/dev/null 2>&1
}

run_command() {
  "$@" || { echo "Command failed: $*"; exit 1; }
}

install_cava_from_fork() {
  log "Installing CAVA from the fork..."
  CAVA_REPO="https://github.com/theshepherdmatt/cava.git"
  PLUGIN_DIR="$(pwd)"
  CAVA_BUILD_DIR="/tmp/cava_build_$$"
  CAVA_PREFIX="$PLUGIN_DIR/cava"

  rm -rf "$CAVA_BUILD_DIR" "$CAVA_PREFIX"

  log "Installing build dependencies for CAVA..."
  apt-get install -y \
    libfftw3-dev \
    libasound2-dev \
    libncursesw5-dev \
    libpulse-dev \
    libtool \
    automake \
    autoconf \
    gcc \
    make \
    pkg-config \
    libiniparser-dev

  git clone "$CAVA_REPO" "$CAVA_BUILD_DIR"
  cd "$CAVA_BUILD_DIR"
  autoreconf -fi
  ./configure --prefix="$CAVA_PREFIX"
  make
  make install

  cd "$PLUGIN_DIR"

  mkdir -p "$CAVA_PREFIX/config"
  if [ -f "$CAVA_BUILD_DIR/config/default_config" ]; then
    cp "$CAVA_BUILD_DIR/config/default_config" "$CAVA_PREFIX/config/default_config"
    log "Copied default_config from built CAVA source."
  elif [ -f "./cava_default_config" ]; then
    cp ./cava_default_config "$CAVA_PREFIX/config/default_config"
    log "Copied default_config from plugin root."
  elif [ -f "./quadifyapp/cava_default_config" ]; then
    cp ./quadifyapp/cava_default_config "$CAVA_PREFIX/config/default_config"
    log "Copied default_config from quadifyapp."
  else
    log "Warning: No default cava config found to copy!"
  fi

  rm -rf "$CAVA_BUILD_DIR"

  log "CAVA installed locally in $CAVA_PREFIX."
}

setup_cava_service() {
  log "Setting up CAVA systemd service..."
  CAVA_SERVICE_FILE="/etc/systemd/system/cava.service"
  LOCAL_CAVA_SERVICE="./quadifyapp/service/cava.service"
  if [[ -f "$LOCAL_CAVA_SERVICE" ]]; then
    run_command cp "$LOCAL_CAVA_SERVICE" "$CAVA_SERVICE_FILE"
    run_command systemctl daemon-reload
    run_command systemctl enable cava.service
    log "CAVA service installed and enabled."
  else
    log "Warning: cava.service not found in quadifyapp/service/"
  fi
}

configure_mpd() {
    log_progress "Configuring MPD for FIFO..."
    MPD_CONF_FILE="/volumio/app/plugins/music_service/mpd/mpd.conf.tmpl"
    FIFO_OUTPUT='
audio_output {
    type            "fifo"
    name            "my_fifo"
    path            "/tmp/cava.fifo"
    format          "44100:16:2"
}'
    if grep -q "/tmp/cava.fifo" "$MPD_CONF_FILE"; then
        log_message "info" "FIFO output config already in MPD conf."
    else
        echo "$FIFO_OUTPUT" >> "$MPD_CONF_FILE"
        log_message "success" "Added FIFO output to MPD conf."
    fi
    run_command systemctl restart mpd
    log_message "success" "MPD restarted with updated FIFO config."
    show_random_tip
}

log "Installing system dependencies..."
apt-get update
apt-get install -y python3 python3-pip python3-venv \
  libjpeg-dev zlib1g-dev libfreetype6-dev \
  i2c-tools python3-smbus libgirepository1.0-dev \
  pkg-config libcairo2-dev libffi-dev build-essential \
  libxml2-dev libxslt1-dev libssl-dev lirc lsof \
  python3-gi python3-cairo gir1.2-gtk-3.0

log "Cleaning up Python packaging issues..."
pip3 uninstall -y importlib-metadata setuptools python-socketio socketio socketIO-client >/dev/null 2>&1 || true

log "Upgrading pip and setuptools..."
python3 -m pip install --upgrade pip setuptools importlib-metadata

log "Installing Python dependencies from requirements.txt..."
python3 -m pip install --upgrade --ignore-installed -r ./quadifyapp/requirements.txt

log "Installing Node.js dependencies..."
if [ -f package.json ]; then
  npm install --production --silent
  log "Node.js dependencies installed."
else
  log "Warning: package.json not found, skipping npm install."
fi

log "Enabling I2C/SPI overlays in /boot/userconfig.txt..."
CONFIG_FILE="/boot/userconfig.txt"
touch "$CONFIG_FILE"
grep -qxF 'dtparam=spi=on' "$CONFIG_FILE" || echo 'dtparam=spi=on' >> "$CONFIG_FILE"
grep -qxF 'dtparam=i2c_arm=on' "$CONFIG_FILE" || echo 'dtparam=i2c_arm=on' >> "$CONFIG_FILE"
modprobe i2c-dev || true
modprobe spi-bcm2835 || true

log "Adding IR overlay to userconfig.txt (gpio27)..."
grep -qxF 'dtoverlay=gpio-ir,gpio_pin=27' "$CONFIG_FILE" || echo 'dtoverlay=gpio-ir,gpio_pin=27' >> "$CONFIG_FILE"

log "Configuring LIRC options for GPIO IR (gpio27)..."
LIRC_OPTIONS="/etc/lirc/lirc_options.conf"
if [ -f "$LIRC_OPTIONS" ]; then
  sed -i 's|^driver\s*=.*|driver = default|' "$LIRC_OPTIONS"
  sed -i 's|^device\s*=.*|device = /dev/lirc0|' "$LIRC_OPTIONS"
  log "Updated existing lirc_options.conf with gpio IR settings."
else
  log "Creating new lirc_options.conf with gpio IR settings."
  cat <<EOF > "$LIRC_OPTIONS"
[lircd]
nodaemon        = False
driver          = default
device          = /dev/lirc0
EOF
fi
systemctl restart lircd
log "LIRC service restarted with updated configuration."

log "Setting up systemd services..."
SERVICES=("quadify.service" "ir_listener.service" "early_led8.service" "cava.service")
for svc in "${SERVICES[@]}"; do
  if [ -f "quadifyapp/service/$svc" ]; then
    cp "quadifyapp/service/$svc" "/etc/systemd/system/$svc"
    chmod 644 "/etc/systemd/system/$svc"
    systemctl daemon-reload
    systemctl enable "$svc"
    if [ "$svc" == "quadify.service" ]; then
      systemctl restart "$svc" || log "$svc could not be started"
    else
      log "$svc enabled but not started (will be controlled via plugin UI)"
    fi
  else
    log "$svc not found, skipping..."
  fi
done

log "Configuring MPD with FIFO output..."
configure_mpd

log "Installing CAVA..."
install_cava_from_fork
setup_cava_service

log "Setting permissions for plugin folder..."
chown -R volumio:volumio .
chmod -R 755 .

python3 -c "import importlib_metadata, setuptools, socketio; print('Packaging OK:', hasattr(importlib_metadata, 'MetadataPathFinder'), setuptools.__version__, hasattr(socketio, 'Client'))" || { echo 'Packaging is still broken!'; exit 1; }

log "Quadify installation complete. Configure features via plugin UI."
