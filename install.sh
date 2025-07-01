#!/bin/bash
set -e

echo "Installing Python and plugin dependencies..."

apt-get update
apt-get install -y python3 python3-pip

# Move to plugin quadify folder where requirements.txt is
cd "$(dirname "$0")/quadify"

# Upgrade pip and install Python dependencies
pip3 install --upgrade pip
pip3 install -r requirements.txt

# Run your custom Quadify install script explicitly
chmod +x ./quadify_install.sh
./quadify_install.sh

echo "Quadify plugin installation complete."
