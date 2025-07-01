
# Quadify — Volumio 3 Plugin

**Quadify** is a comprehensive hardware interface plugin for **Volumio 3** that adds:

- Advanced OLED/LCD display with Now Playing info, album art, menus, screensavers, system status, and more
- Rotary encoder support for volume, track navigation, and menu scrolling
- MCP23017 I²C button and LED matrix support for full customizable controls
- IR remote control compatibility with popular remotes
- Seamless integration with Volumio's plugin system — clean startup/shutdown, systemd services, and native plugin paths

---

## Features

| Feature               | Description                                                       |
|-----------------------|-------------------------------------------------------------------|
| OLED/LCD Display      | Rich playback info and UI on secondary display                    |
| Rotary Encoder        | Hardware volume and menu control                                  |
| MCP23017 Button/LED   | Expandable custom button and LED panel via I²C                    |
| IR Remote             | Easy remote control setup and diagnostics                         |
| Full Plugin Integration | Systemd services, UI configuration, and plugin-native file paths |

---

## Installation

### Step 1: SSH into your Volumio device

Open a terminal and connect via SSH:

```bash
ssh volumio@<volumio-ip-address>
````

### Step 2: Prepare the plugin directory

Create the system\_controller plugin folder if it doesn’t exist, and set the correct ownership:

```bash
sudo mkdir -p /data/plugins/system_controller
sudo chown volumio:volumio /data/plugins/system_controller
```

### Step 3: Clone the Quadify repository

```bash
cd /data/plugins/system_controller
sudo git clone https://github.com/theshepherdmatt/Quadify-Plugin.git quadify
cd quadify
```

### Step 4: Install Quadify

Make sure the install script is executable and run it:

```bash
chmod +x ./install.sh
sudo /data/plugins/system_controller/quadify/install.sh
```

> **Note:** If you encounter a `command not found` error when running `sudo ./install.sh`, use the full path as above.

### Step 5: Reboot your device

A reboot may be required for hardware and services to initialize properly.

### Step 6: Configure via Volumio UI

Use the Volumio Web UI plugin settings page to configure display, rotary, buttons, and remote options.

---

## Compatibility

* Built and tested for **Volumio 3.x** on Raspberry Pi and similar SBCs
* Not tested on Volumio Bookworm or Buster releases
* Uses plugin-relative paths — no hardcoded `/home/volumio/Quadify`

---

## Documentation & Support

* Explore the [Quadify Wiki](https://github.com/theshepherdmatt/Quadify-Plugin/wiki) for guides and FAQs
* Open issues or suggest features via the [GitHub Issues](https://github.com/theshepherdmatt/Quadify-Plugin/issues) page

---

## Credits

Thanks to the Volumio community and all contributors who helped bring Quadify to life!

---
