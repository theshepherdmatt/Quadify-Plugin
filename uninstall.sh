#!/bin/bash
set -e

echo "Uninstalling Quadify plugin..."

# Remove Python packages if needed (optional)
# pip3 uninstall -r requirements.txt -y

# Stop and disable any services Quadify may have created
if systemctl list-units --full -all | grep -q "quadify.service"; then
  systemctl stop quadify.service
  systemctl disable quadify.service
  rm -f /etc/systemd/system/quadify.service
fi

echo "Quadify plugin uninstall complete."