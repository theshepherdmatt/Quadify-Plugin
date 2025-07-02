# Quadify — Volumio 3 Plugin

**Quadify** is a comprehensive hardware interface plugin for **Volumio 3** that adds:

* Advanced OLED/LCD display with Now Playing info, album art, menus, screensavers, system status, and more
* Rotary encoder support for volume, track navigation, and menu scrolling
* MCP23017 I²C button and LED matrix support for full customizable controls
* IR remote control compatibility with popular remotes
* Seamless integration with Volumio's plugin system — clean startup/shutdown, systemd services, and native plugin paths

---

## Features

| Feature                 | Description                                                      |
| ----------------------- | ---------------------------------------------------------------- |
| OLED/LCD Display        | Rich playback info and UI on secondary display                   |
| Rotary Encoder          | Hardware volume and menu control                                 |
| MCP23017 Button/LED     | Expandable custom button and LED panel via I²C                   |
| IR Remote               | Easy remote control setup and diagnostics                        |
| Full Plugin Integration | Systemd services, UI configuration, and plugin-native file paths |

---

## Installation

We’ve streamlined the installation process to minimize manual steps and ensure idempotency.

### Prerequisites

* **SSH access** to your Volumio device
* **Git** and **sudo** privileges
* A valid **SSH key** added to your [GitHub SSH keys](https://github.com/settings/keys)

### Installation Script (Automated)

Instead of manual cloning and permission fixes, we provide a one‑line installer:

```bash
curl -fsSL https://raw.githubusercontent.com/theshepherdmatt/Quadify-Plugin/main/install.sh \
  | sudo bash
```

This does:

1. Creates `/data/plugins/music_service/quadify` (if missing).
2. Clones the plugin repo.
3. Installs all **system**, **Python**, and **Node.js** dependencies.
4. Enables and starts the required systemd services.

After the script completes, it will print **"Quadify installation complete"**.

### (Optional) Manual Steps

If you prefer manual control, follow these steps:

1. **SSH into your Volumio**:

   ```bash
   ssh volumio@<volumio-ip-address>
   ```
2. **Prepare plugin directory**:

   ```bash
   sudo mkdir -p /data/plugins/music_service
   sudo chown volumio:volumio /data/plugins/music_service
   ```
3. **Clone the repository**:

   ```bash
   cd /data/plugins/music_service
   git clone git@github.com:theshepherdmatt/Quadify-Plugin.git quadify
   ```
4. **Run the installer**:

   ```bash
   cd quadify
   sudo chmod +x install.sh
   sudo ./install.sh
   ```
5. **Reboot** (recommended):

   ```bash
   sudo reboot
   ```
6. **Configure via Volumio UI**: enable/disable features and adjust settings in **Plugins → Installed Plugins → Quadify**.

---

## Compatibility

* **Volumio 3.x** on Raspberry Pi and similar SBCs
* Not tested on Bookworm or Buster releases

---

## Documentation & Support

* Wiki: [https://github.com/theshepherdmatt/Quadify-Plugin/wiki](https://github.com/theshepherdmatt/Quadify-Plugin/wiki)
* Issues: [https://github.com/theshepherdmatt/Quadify-Plugin/issues](https://github.com/theshepherdmatt/Quadify-Plugin/issues)

---

## Credits

Thanks to the Volumio community and all contributors who helped bring Quadify to life!
