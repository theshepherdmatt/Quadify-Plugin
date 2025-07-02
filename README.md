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
| OLED Display        | Rich playback info and UI on secondary display                   |
| Rotary Encoder          | Hardware volume and menu control                                 |
| MCP23017 Button/LED     | Expandable custom button and LED panel via I²C                   |
| IR Remote               | Easy remote control setup and diagnostics                        |
| Full Plugin Integration | Systemd services, UI configuration, and plugin-native file paths |

---

## Installation (1-Line, Fully Automated)

SSH into your Volumio device and **run this command**:

```bash
sudo mkdir -p /data/plugins/music_service \
  && cd /data/plugins/music_service \
  && sudo git clone https://github.com/theshepherdmatt/Quadify-Plugin.git quadify \
  && cd quadify \
  && sudo chmod +x install.sh \
  && sudo ./install.sh
```

* **Clones Quadify to the correct plugin folder**
* **Installs all system, Python, and Node.js dependencies**
* **Enables systemd services for startup**
* **No SSH keys required for public repo**
* Prints **"Quadify installation complete"** when done.

> **Reboot after install for hardware and services to initialize.
> Configure via Volumio’s Web UI in Plugins → Installed Plugins → Quadify.**

---

## Compatibility

* **Volumio 3.x** on Raspberry Pi and similar SBCs
* Not tested on Bookworm or Buster releases

---

## Documentation & Support

* [Quadify Wiki](https://github.com/theshepherdmatt/Quadify-Plugin/wiki)
* [GitHub Issues](https://github.com/theshepherdmatt/Quadify-Plugin/issues)

---

## Credits

Thanks to the Volumio community and all contributors who helped bring Quadify to life!

---
