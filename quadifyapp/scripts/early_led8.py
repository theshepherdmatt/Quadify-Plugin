#!/usr/bin/env python3
import os
import sys
import time
import yaml
from smbus2 import SMBus

# MCP23017 registers
IODIRA = 0x00
GPIOA  = 0x12

DEFAULT_ADDR = 0x20  # fallback if not in config

def _int_auto(x):
    """int that accepts '0x20', '32', etc."""
    if isinstance(x, int):
        return x
    return int(str(x), 0)

def load_mcp_addr():
    # 1) ENV overrides (optional)
    if os.getenv("MCP23017_ADDRESS"):
        try:
            return _int_auto(os.getenv("MCP23017_ADDRESS"))
        except Exception:
            pass

    # 2) Try config.yaml (several likely locations/keys)
    candidates = [
        os.getenv("QUADIFY_CONFIG"),
        "/data/plugins/system_hardware/quadify/quadifyapp/config.yaml",
        os.path.join(os.path.dirname(__file__), "..", "config.yaml"),
        os.path.join(os.path.dirname(__file__), "..", "..", "config.yaml"),
    ]
    keys_to_try = [
        ("mcp23017_address",),            # top-level
        ("mcp23017", "address"),          # nested
        ("hardware", "mcp23017_address"),
        ("display", "mcp23017_address"),
    ]

    for path in [p for p in candidates if p]:
        try:
            with open(path, "r") as f:
                cfg = yaml.safe_load(f) or {}
            for key_path in keys_to_try:
                d = cfg
                for k in key_path:
                    if isinstance(d, dict) and k in d:
                        d = d[k]
                    else:
                        d = None
                        break
                if d is not None:
                    return _int_auto(d)
        except Exception:
            pass

    return DEFAULT_ADDR

# Boot indicator LED. NOTE: the original red LED8 (GPIOA A0) is dead hardware
# on this unit, so we use LED2 (A6) instead. All LEDs are ACTIVE-HIGH, so drive
# A6 high to light it. (0b01000000 = bit6 = A6 = LED2.)
BOOT_LED_BIT = 0b01000000

def main():
    addr = load_mcp_addr()
    # Runs ultra-early (sysinit), so the I2C bus may not be ready for the first
    # moment — retry briefly instead of giving up on the first failure.
    last_err = None
    for _ in range(20):                       # up to ~10s
        try:
            with SMBus(1) as bus:
                bus.write_byte_data(addr, IODIRA, 0x00)        # Port A => outputs
                bus.write_byte_data(addr, GPIOA, BOOT_LED_BIT)  # LED2 (A6) ON
            print(f"early_led8: boot LED (LED2/A6) ON at MCP23017 0x{addr:02X}")
            return
        except Exception as e:
            last_err = e
            time.sleep(0.5)
    print(f"early_led8: failed at 0x{addr:02X}: {last_err}")
    sys.exit(1)

if __name__ == "__main__":
    main()

