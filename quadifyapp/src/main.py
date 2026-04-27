#!/usr/bin/env python3
# src/main.py

import RPi.GPIO as GPIO
GPIO.setwarnings(False)

import logging
import os
import signal
import sys
import threading
import time

import yaml

# Only DisplayManager is imported up-front so the splash can hit the OLED
# as fast as possible. The rest (luma's been pulled in already via
# DisplayManager, but socketio / transitions / screen modules / rotary /
# icon converter) are deferred until after the first draw — see main().
from display.display_manager import DisplayManager
from startup import BootCoordinator, CommandDispatcher, start_command_server


CONFIG_PATH = "/data/plugins/system_hardware/quadify/quadifyapp/config.yaml"
SPLASH_MAX_WAIT = 4.0  # hard cap before we assume Volumio isn't going to talk

# Per-screen rotary volume steps preserved from the original behaviour:
# original is symmetric, the rest are intentionally asymmetric.
PLAYBACK_VOLUME_STEPS = {
    "original":        ("original_screen", 40, -40),
    "modern":          ("modern_screen", 10, -20),
    "minimal":         ("minimal_screen", 10, -20),
    "vuscreen":        ("vu_screen",      10, -20),
    "digitalvuscreen": ("digitalvu_screen", 10, -20),
    "webradio":        ("webradio_screen", 10, -20),
}


def load_config(path: str) -> dict:
    if not os.path.isfile(path):
        return {}
    with open(path, "r") as f:
        return yaml.safe_load(f) or {}


def turn_off_led8(log: logging.Logger) -> None:
    try:
        import smbus2
        bus = smbus2.SMBus(1)
        try:
            current = bus.read_byte_data(0x20, 0x12)
            bus.write_byte_data(0x20, 0x12, current & 0b11111110)
        finally:
            bus.close()
    except Exception as e:
        log.debug("LED8 off skipped: %s", e)


def make_rotary_handlers(mode_manager):
    def on_rotate(direction: int):
        mode = mode_manager.get_mode()
        spec = PLAYBACK_VOLUME_STEPS.get(mode)
        if spec is not None:
            attr, up, down = spec
            screen = getattr(mode_manager, attr, None)
            if screen:
                screen.adjust_volume(up if direction == 1 else down)
            return
        CommandDispatcher._handle_scroll(mode_manager, mode, direction)

    def on_press():
        CommandDispatcher._handle_select(mode_manager, mode_manager.get_mode())

    def on_long_press():
        if mode_manager.get_mode() == "menu":
            mode_manager.trigger("to_clock")
        else:
            mode_manager.trigger("back")

    return on_rotate, on_press, on_long_press


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    log = logging.getLogger("QuadifyMain")

    config = load_config(CONFIG_PATH)
    display_config = config.get("display", {})
    volumio_cfg = config.get("volumio", {})

    # 1. Display first. Once this returns SPI is up, so we can draw.
    display_manager = DisplayManager(display_config)

    # 2. Earliest possible draw: pre-splash text appears in ~10ms while the
    #    239KB logo GIF loads in step 4. The user sees feedback essentially
    #    the moment SPI is alive.
    try:
        font_key = "menu_font_bold" if "menu_font_bold" in display_manager.fonts else "default"
        display_manager.display_text("STARTING…", (84, 26), font_key=font_key)
    except Exception as e:
        log.debug("Pre-splash text failed: %s", e)

    # 3. Heavy imports deferred until after first draw. These pull in
    #    socketio / transitions / all screen modules — multiple seconds
    #    on a Pi 3/4 — and the user is already looking at the splash by now.
    #    NOTE: convert2 (icon fetcher) is deliberately NOT imported here.
    #    It used to run on every boot via convert_icons_main(); on a cold
    #    start before Volumio's API was up, that overwrote the manifest
    #    with zero entries. It now lives behind quadify-icon-fetch.service
    #    and is run on demand (or by the plugin install hook).
    from network.volumio_listener import VolumioListener
    from display.screens.clock import Clock
    from managers.mode_manager import ModeManager
    from managers.manager_factory import ManagerFactory
    from controls.rotary_control import RotaryControl

    # 4. Logo splash replaces the pre-splash text.
    #    Inline draw so animated/palette GIFs are handled the same way
    #    DisplayManager.show_logo handles its animated path: convert→resize→
    #    convert. The bare display_image call did resize→convert which
    #    produces a near-black image for palette-mode GIFs.
    splash_path = display_config.get("logo_path")
    if splash_path:
        try:
            from PIL import Image as _Image  # local import; PIL already in
            img = _Image.open(splash_path)
            if getattr(img, "is_animated", False):
                img.seek(0)
            if img.mode == "RGBA":
                bg = _Image.new("RGB", img.size, (0, 0, 0))
                bg.paste(img, mask=img.split()[3])
                img = bg
            else:
                img = img.convert("RGB")
            oled = display_manager.oled
            if oled is not None:
                if img.size != oled.size:
                    img = img.resize(oled.size, _Image.LANCZOS)
                oled.display(img.convert(oled.mode))
                log.info("Splash logo drawn from %s", splash_path)
            else:
                log.warning("Splash skipped: OLED not initialised.")
        except Exception as e:
            log.error("Splash render failed: %s", e)

    # 5. Listener starts connecting in parallel with everything below.
    volumio_listener = VolumioListener(
        host=volumio_cfg.get("host", "localhost"),
        port=volumio_cfg.get("port", 3000),
    )

    # 6. Boot coordinator: subscribe for first state. (Splash already drawn.)
    boot = BootCoordinator(
        display_manager=display_manager,
        volumio_listener=volumio_listener,
        logo_path=None,  # already drawn in step 4
        max_wait=SPLASH_MAX_WAIT,
    )
    boot.attach()

    # 7. Single command server. During boot, only shutdown + skip-splash work.
    dispatcher = CommandDispatcher(
        volumio_listener=volumio_listener,
        on_skip_splash=boot.skip,
    )
    start_command_server(dispatcher)

    # 8. Rotary press during boot also skips the splash.
    rotary_control = RotaryControl(
        rotation_callback=lambda d: None,
        button_callback=boot.skip,
        long_press_callback=lambda: None,
        long_press_threshold=2.5,
    )
    threading.Thread(target=rotary_control.start, daemon=True,
                     name="Rotary").start()

    # 9. Cheap housekeeping while the splash is up.
    turn_off_led8(log)

    # 10. Build the full UI stack while the splash is still on screen.
    clock_config = config.get("clock", {})
    clock = Clock(display_manager, clock_config, volumio_listener)
    clock.logger = logging.getLogger("Clock")
    clock.logger.setLevel(logging.INFO)

    mode_manager = ModeManager(
        display_manager=display_manager,
        clock=clock,
        volumio_listener=volumio_listener,
        preference_file_path="../preference.json",
        config=config,
    )
    factory = ManagerFactory(
        display_manager=display_manager,
        volumio_listener=volumio_listener,
        mode_manager=mode_manager,
        config=config,
    )
    factory.setup_mode_manager()
    volumio_listener.mode_manager = mode_manager
    volumio_listener.menu_manager = mode_manager.menu_manager

    # 8. Wait for splash to resolve (state | timeout | skip).
    handoff = boot.wait_for_handoff()
    log.info("Boot handoff: reason=%s", handoff["reason"])

    state = handoff["state"] or {}
    status = (state.get("status") or "").lower()

    if status == "play":
        # ModeManager's own pushState handler usually routed to the right
        # playback screen already. If we missed the live event (state was only
        # in the listener's buffer), replay it now.
        if mode_manager.get_mode() == "boot":
            mode_manager.process_state_change(volumio_listener, state)
        if mode_manager.get_mode() == "boot":
            mode_manager.to_clock()  # safety net: somehow nothing routed
    else:
        # stop / pause / unknown / no-state-at-all → land on the clock face.
        # Replay the buffered state first so first_state_handoff is consumed
        # cleanly (otherwise the next real event still thinks it's first).
        if state:
            mode_manager.process_state_change(volumio_listener, state)
        if mode_manager.get_mode() == "boot":
            mode_manager.to_clock()

    # 9. Live UI: route real input through the dispatcher / mode_manager.
    dispatcher.attach_mode_manager(mode_manager)

    on_rotate, on_press, on_long_press = make_rotary_handlers(mode_manager)
    rotary_control.rotation_callback = on_rotate
    rotary_control.button_callback = on_press
    rotary_control.long_press_callback = on_long_press

    # 10. Graceful shutdown.
    def _on_sigterm(signum, frame):
        log.info("SIGTERM received; shutting down.")
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, _on_sigterm)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        log.info("Shutting down Quadify.")
    finally:
        for name, fn in (
            ("rotary",   rotary_control.stop),
            ("listener", volumio_listener.stop),
            ("clock",    clock.stop),
            ("display",  display_manager.cleanup),
        ):
            try:
                fn()
            except Exception as e:
                log.warning("Error stopping %s: %s", name, e)


if __name__ == "__main__":
    main()
