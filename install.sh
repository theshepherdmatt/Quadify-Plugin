#!/bin/bash
set -e

echo "Installing Python and plugin dependencies..."

apt-get update
apt-get install -y python3 python3-pip

# Install Python packages
cd "$(dirname "$0")/quadify"
pip3 install --upgrade pip
pip3 install -r requirements.txt

# Run Quadify’s custom setup
if [ -f ./install.sh ]; then
  echo "Running Quadify custom install script..."
  chmod +x ./install.sh
  ./install.sh
fi

echo "Quadify plugin installation complete."
