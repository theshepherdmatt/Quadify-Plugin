#!/usr/bin/env python3
"""
Ultra-early splash for Quadify.

Runs as a oneshot during sysinit, before mpd / samba / Volumio backend start
saturating SD I/O on boot. Imports only luma + PIL (+ yaml for config),
draws the configured logo to the SSD1322, and exits. The OLED retains its
last frame in display RAM, so the logo stays on screen until the main
quadify.service starts and overdraws it.

The whole point: get *something* on screen as fast as physically possible
after power-on so the user knows the unit is alive.
"""

import os
import sys


CONFIG_PATH = "/data/plugins/system_hardware/quadify/quadifyapp/config.yaml"


def _resolve_rotation(cfg):
    """Mirror DisplayManager._resolve_rotation so the splash matches."""
    raw = cfg.get("display_rotate")
    if raw is None:
        raw = (cfg.get("display") or {}).get("rotation")
    try:
        n = int(str(raw).strip())
        if n in (0, 1, 2, 3):
            return n
        return (n // 90) % 4
    except Exception:
        return 0


def _load_config():
    try:
        import yaml
        with open(CONFIG_PATH, "r") as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        print(f"[splash] config read failed: {e}", file=sys.stderr)
        return {}


def main():
    cfg = _load_config()
    display_cfg = cfg.get("display") or {}
    logo_path = display_cfg.get("logo_path")
    if not logo_path or not os.path.isfile(logo_path):
        print(f"[splash] logo not found: {logo_path!r}", file=sys.stderr)
        return 0  # never fail boot over a splash

    rotate = _resolve_rotation(cfg)

    try:
        from luma.core.interface.serial import spi
        from luma.oled.device import ssd1322
        from PIL import Image
    except Exception as e:
        print(f"[splash] import failed: {e}", file=sys.stderr)
        return 0

    try:
        serial = spi(device=0, port=0)
        oled = ssd1322(serial, width=256, height=64, rotate=rotate)
    except Exception as e:
        print(f"[splash] SPI/OLED init failed: {e}", file=sys.stderr)
        return 0

    try:
        img = Image.open(logo_path)
        if getattr(img, "is_animated", False):
            img.seek(0)
        if img.mode == "RGBA":
            bg = Image.new("RGB", img.size, (0, 0, 0))
            bg.paste(img, mask=img.split()[3])
            img = bg
        if img.size != oled.size:
            img = img.resize(oled.size, Image.LANCZOS)
        oled.display(img.convert(oled.mode))
        print("[splash] logo drawn", file=sys.stderr)
    except Exception as e:
        print(f"[splash] render failed: {e}", file=sys.stderr)

    # Intentionally do NOT call serial.cleanup() — we want the OLED to keep
    # showing the splash until quadify.service overdraws it.
    return 0


if __name__ == "__main__":
    sys.exit(main())
