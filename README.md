## Quadify Volumio 3 Plugin

**Quadify** brings a complete hardware interface to Volumio 3, including advanced display, rotary encoder, MCP23017 button/LED, and IR remote support—all wrapped up in a single, easy-to-install plugin.

---

### What is Quadify?

Quadify extends your Volumio system with:

* **OLED/LCD Display Layer:** Now Playing info, menus, album art, screensavers, system status, and more.
* **Rotary Encoder Support:** Volume, track navigation, menu scrolling, etc.
* **MCP23017 Button/LED Matrix:** Full custom button and LED panel support via I²C expander.
* **IR Remote:** Easily configure and use popular remotes with Volumio.
* **Full integration:** Clean startup/shutdown, systemd services, UI configuration, all paths plugin-native.

---

### Installation

1. **SSH into your Volumio device.**
2. Clone this repository or install via the Volumio plugin system.
3. Run the installer from the plugin directory:

   ```bash
   cd /data/plugins/system_controller/quadify
   sudo ./install.sh
   ```
4. Reboot if prompted.
5. Configure options via the Volumio UI.

Full install instructions and troubleshooting are [in the Wiki](https://github.com/theshepherdmatt/Quadify-Plugin/wiki).

---

### Compatibility

* Designed for **Volumio 3.x** on Raspberry Pi and similar SBC hardware.
* Not tested on Bookworm or earlier Buster-based Volumio builds.
* Paths and services are plugin-relative (no `/home/volumio/Quadify` hardcoding).

---

### Documentation & Support

* [Quadify Wiki](https://github.com/theshepherdmatt/Quadify-Plugin/wiki)
* [Open an Issue](https://github.com/theshepherdmatt/Quadify-Plugin/issues) for help or suggestions.

---

### Credits

Thanks to the Volumio community, plugin pioneers, and everyone providing feedback and support!

