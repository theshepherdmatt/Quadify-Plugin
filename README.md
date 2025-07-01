Here’s the updated README section with your install troubleshooting note added:

````markdown
## Quadify Volumio 3 Plugin

**Quadify** brings a complete hardware interface to Volumio 3, including advanced display, rotary encoder, MCP23017 button/LED, and IR remote support — all wrapped up in a single, easy-to-install plugin.

---

### What is Quadify?

Quadify extends your Volumio system with:

* **OLED/LCD Display Layer:** Now Playing info, menus, album art, screensavers, system status, and more.
* **Rotary Encoder Support:** Volume control, track navigation, menu scrolling, etc.
* **MCP23017 Button/LED Matrix:** Full custom button and LED panel support via I²C expander.
* **IR Remote:** Easily configure and use popular remotes with Volumio.
* **Full integration:** Clean startup/shutdown, systemd services, UI configuration, all plugin-native paths.

---

### Installation

1. **SSH into your Volumio device.**

2. **Create the plugin directory (if it doesn't exist) and set ownership:**

   ```bash
   sudo mkdir -p /data/plugins/system_controller
   sudo chown volumio:volumio /data/plugins/system_controller
````

3. **Clone the Quadify repository into the plugin directory:**

   ```bash
   cd /data/plugins/system_controller
   git clone https://github.com/theshepherdmatt/Quadify-Plugin.git quadify
   cd quadify
   ```

4. **Run the installer:**

   ```bash
   # Ensure the install script is executable
   chmod +x ./install.sh

   # Run the install script with full path to avoid "command not found" issues
   sudo /data/plugins/system_controller/quadify/install.sh
   ```

   > **Note:** If you get a `command not found` error running `sudo ./install.sh`, try running it with the full path as shown above.

5. **Reboot your device if prompted.**

6. **Configure options via the Volumio UI plugin settings page.**

For detailed installation instructions and troubleshooting, please visit the [Quadify Wiki](https://github.com/theshepherdmatt/Quadify-Plugin/wiki).

---

### Compatibility

* Designed specifically for **Volumio 3.x** on Raspberry Pi and similar single-board computers.
* Not tested on Volumio Bookworm or Buster-based builds.
* All paths and services are plugin-relative, avoiding hardcoded `/home/volumio/Quadify` references.

---

### Documentation & Support

* Visit the [Quadify Wiki](https://github.com/theshepherdmatt/Quadify-Plugin/wiki) for documentation and FAQs.
* Report issues or suggest features via the [GitHub Issues page](https://github.com/theshepherdmatt/Quadify-Plugin/issues).

---

### Credits

Special thanks to the Volumio community, early plugin pioneers, and all users providing feedback and support!

---
