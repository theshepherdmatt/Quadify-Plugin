# src/display/screens/vu_screen.py

import os
import math
import logging
import threading
import time
from PIL import Image, ImageDraw, ImageEnhance, ImageFont

from managers.menus.base_manager import BaseManager


class VUScreen(BaseManager):
    """
    Analogue VU-meter screen for Quadify.

    Visuals adapted from the moOde "VU.png" build:
      - EMA-smoothed needle ballistics (heavy analog feel)
      - Asymmetric arc angles calibrated for the new vuscreen.png
      - Scrolling artist + title with thin black shadow

    Data sources stay Quadify-native:
      - VolumioListener for state changes
      - CAVA fifo at /tmp/display.fifo (text, ";"-separated, ~36 bars 0-255)
    """

    # ----- needle geometry (calibrated for the new vuscreen.png) -----
    LEFT_PIVOT    = (64,  70)   # px; sits just below the 64-px image edge
    RIGHT_PIVOT   = (192, 70)
    NEEDLE_LEN    = 37
    ANGLE_MIN     = -65         # signal=0   (~-20 dB mark)
    ANGLE_MAX     = +35         # signal=100 (~+6  dB mark)

    # ----- style -----
    NEEDLE_COLOR  = (255, 255, 255)   # full bright — focal element
    NEEDLE_WIDTH  = 2
    PIVOT_RADIUS  = 2
    EMA_PREV      = 0.75
    EMA_CURR      = 0.25

    # ----- brightness hierarchy (SSD1322 is 4-bit greyscale, 16 levels) -----
    BG_BRIGHTNESS = 0.70              # dim the VU.png so foreground pops
    FILL_TITLE    = (255, 255, 255)   # primary line — full bright
    FILL_ARTIST   = (200, 200, 200)   # secondary line — medium grey
    FILL_INFO     = (160, 160, 160)   # tertiary line — dim grey

    # ----- spectrum source -----
    FIFO_PATH     = "/tmp/display.fifo"
    BANDS         = 36           # CAVA is configured for 36 bars in Quadify

    # ----- text layout -----
    # Tune these if the title kisses the top of the meter arch on your art.
    # Going more negative on ARTIST_Y crops the cap; bigger TITLE_Y pushes
    # the title down toward the arch.
    ARTIST_Y      = -2           # was -1; nudged up 1 px
    TITLE_Y       = 9            # was 11; nudged up 2 px to clear the arch
    INFO_Y        = 52
    SCROLL_PX     = 1            # scroll speed (px / frame) for long text

    def __init__(self, display_manager, volumio_listener, mode_manager):
        super().__init__(display_manager, volumio_listener, mode_manager)
        self.display_manager  = display_manager
        self.volumio_listener = volumio_listener
        self.mode_manager     = mode_manager
        self.mode_name        = "vuscreen"

        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(logging.INFO)

        # ----- fonts (named keys come from config.yaml display.fonts) -----
        # font_title is split out from font_info so each line can be sized
        # independently. Info line uses volume_small (size 8) so the
        # vol/sample-rate/bit-depth strip doesn't shout for attention.
        self.font_artist = display_manager.fonts.get("artist_font",  ImageFont.load_default())
        self.font_title  = display_manager.fonts.get("data_font",    ImageFont.load_default())
        self.font_info   = display_manager.fonts.get("volume_small", ImageFont.load_default())

        # ----- background image -----
        self.vu_background = self._load_background()

        # ----- spectrum + needle ballistics -----
        self.spectrum_bars = [0] * self.BANDS
        self.left_smooth   = 0.0
        self.right_smooth  = 0.0
        self._spec_lock    = threading.Lock()

        # ----- playback state -----
        self.latest_state     = None
        self.current_state    = None
        self.state_lock       = threading.Lock()
        self.update_event     = threading.Event()
        self.stop_event       = threading.Event()
        self.is_active        = False
        self.last_update_time = time.time()

        # ----- scrolling state -----
        self.scroll_offset_artist = 0
        self.scroll_offset_title  = 0

        # ----- threads -----
        self.spectrum_thread  = None
        self.update_thread    = None
        self.running_spectrum = False

        if self.volumio_listener:
            self.volumio_listener.state_changed.connect(self.on_volumio_state_change)
        self.logger.info("VUScreen initialised.")

    # ------------------------------------------------------------------
    #  Asset loading
    # ------------------------------------------------------------------

    def _load_background(self):
        oled = getattr(self.display_manager, "oled", None)
        size = (oled.width, oled.height) if oled else (256, 64)

        cfg = getattr(self.display_manager, "config", {}) or {}
        cfg_path = None
        d = cfg.get("display") if isinstance(cfg, dict) else None
        if isinstance(d, dict):
            cfg_path = d.get("vuscreen_path")
        if cfg_path is None and isinstance(cfg, dict):
            cfg_path = cfg.get("vuscreen_path")

        assets_root = os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..", "..", "assets")
        )
        candidates = [
            cfg_path,
            os.path.join(assets_root, "images", "pngs", "vuscreen.png"),
            os.path.join(assets_root, "images", "vuscreen.png"),
        ]

        for path in candidates:
            if not path or not os.path.isfile(path):
                continue
            try:
                img = Image.open(path).convert("RGB")
                if img.size != size:
                    img = img.resize(size, Image.LANCZOS)
                if self.BG_BRIGHTNESS != 1.0:
                    img = ImageEnhance.Brightness(img).enhance(self.BG_BRIGHTNESS)
                self.logger.info(
                    f"VUScreen: loaded background '{path}' "
                    f"(dimmed to {self.BG_BRIGHTNESS:.0%})."
                )
                return img
            except Exception as e:
                self.logger.warning(f"VUScreen: could not load '{path}' -> {e}")

        self.logger.warning("VUScreen: no background found; black fallback.")
        return Image.new("RGB", size, "black")

    # ------------------------------------------------------------------
    #  Volumio state
    # ------------------------------------------------------------------

    def on_volumio_state_change(self, sender, state):
        if not self.is_active or self.mode_manager.get_mode() != self.mode_name:
            return
        with self.state_lock:
            if self.current_state and (
                state.get("title")  != self.current_state.get("title") or
                state.get("artist") != self.current_state.get("artist")
            ):
                self.scroll_offset_artist = 0
                self.scroll_offset_title  = 0
            self.latest_state = state
        self.update_event.set()

    # ------------------------------------------------------------------
    #  CAVA FIFO reader
    # ------------------------------------------------------------------

    def _read_fifo(self):
        retry_delay = 1.0
        self.logger.info(f"VUScreen: spectrum reader started -> {self.FIFO_PATH}")
        while self.running_spectrum:
            if not os.path.exists(self.FIFO_PATH):
                time.sleep(retry_delay)
                continue
            try:
                with open(self.FIFO_PATH, "r") as fifo:
                    for line in fifo:
                        if not self.running_spectrum:
                            break
                        bars = [int(x) for x in line.strip().split(";") if x.isdigit()]
                        if bars:
                            with self._spec_lock:
                                self.spectrum_bars = bars
            except Exception as e:
                self.logger.error(f"VUScreen: FIFO read error -> {e}")
                time.sleep(retry_delay)
        self.logger.info("VUScreen: spectrum reader exiting.")

    # ------------------------------------------------------------------
    #  Update loop (~30 fps)
    # ------------------------------------------------------------------

    def _update_loop(self):
        self.logger.info("VUScreen: update loop started.")
        while not self.stop_event.is_set():
            triggered = self.update_event.wait(timeout=0.033)
            with self.state_lock:
                if triggered and self.latest_state:
                    self.current_state = self.latest_state.copy()
                    self.latest_state  = None
                    self.update_event.clear()
                elif self.current_state:
                    # Advance synthetic seek while playing so any elapsed
                    # display stays accurate between pushState events.
                    status       = (self.current_state.get("status") or "").lower()
                    duration_val = self.current_state.get("duration")
                    try:
                        duration_ok = int(duration_val) > 0
                    except Exception:
                        duration_ok = False
                    if status == "play" and duration_ok:
                        elapsed  = time.time() - self.last_update_time
                        seek_val = int(self.current_state.get("seek") or 0)
                        self.current_state["seek"] = seek_val + int(elapsed * 1000)
                self.last_update_time = time.time()

            if (
                self.is_active
                and self.mode_manager.get_mode() == self.mode_name
                and self.current_state
            ):
                self._draw()
        self.logger.info("VUScreen: update loop exiting.")

    # ------------------------------------------------------------------
    #  Geometry / text helpers
    # ------------------------------------------------------------------

    def _needle_tip(self, pivot, signal_0_100):
        t   = max(0.0, min(float(signal_0_100), 100.0)) / 100.0
        deg = self.ANGLE_MIN + t * (self.ANGLE_MAX - self.ANGLE_MIN)
        rad = math.radians(deg)
        px, py = pivot
        return (
            int(px + self.NEEDLE_LEN * math.sin(rad)),
            int(py - self.NEEDLE_LEN * math.cos(rad)),
        )

    @staticmethod
    def _shadow_text(draw, xy, text, font, fill="white"):
        x, y = xy
        draw.text((x + 1, y + 1), text, font=font, fill="black")
        draw.text((x,     y    ), text, font=font, fill=fill)

    @staticmethod
    def _measure(font, text):
        try:
            return int(font.getlength(text))
        except AttributeError:
            bbox = font.getbbox(text)
            return (bbox[2] - bbox[0]) if bbox else 0

    def _draw_scrolling_text(self, base_image, text, font, y, clip_width,
                             scroll_offset, fill="white", with_shadow=False):
        """
        If text fits clip_width, centre it. Otherwise scroll left by SCROLL_PX
        per call and return the new offset. Cropping the existing background
        region keeps the VU artwork visible behind the marquee.
        """
        if not text:
            return 0

        text_w = self._measure(font, text)
        try:
            line_h = font.getbbox("Ay")[3]
        except Exception:
            line_h = 12

        if text_w <= clip_width:
            draw = ImageDraw.Draw(base_image)
            x = (clip_width - text_w) // 2
            if with_shadow:
                draw.text((x + 1, y + 1), text, font=font, fill="black")
            draw.text((x, y), text, font=font, fill=fill)
            return 0

        GAP        = 30
        cycle      = text_w + GAP
        new_offset = (scroll_offset + self.SCROLL_PX) % cycle

        region_h = line_h + 2
        # Clip y so the crop region stays inside the canvas
        y_clip = max(0, y)
        h_clip = min(region_h, base_image.height - y_clip)
        if h_clip <= 0:
            return new_offset

        region = base_image.crop((0, y_clip, clip_width, y_clip + h_clip))
        rdraw  = ImageDraw.Draw(region)
        # Re-anchor inside the cropped region: text top is at (y - y_clip)
        ty = y - y_clip

        for rep in range(2):
            tx = -int(new_offset) + rep * cycle
            if tx + text_w < 0 or tx >= clip_width:
                continue
            if with_shadow:
                rdraw.text((tx + 1, ty + 1), text, font=font, fill="black")
            rdraw.text((tx, ty), text, font=font, fill=fill)

        base_image.paste(region, (0, y_clip))
        return new_offset

    # ------------------------------------------------------------------
    #  Main draw
    # ------------------------------------------------------------------

    def _draw(self):
        # ---- ballistics: avg L/R halves of CAVA bars, normalise, EMA ----
        with self._spec_lock:
            bars = list(self.spectrum_bars)

        if len(bars) >= 2:
            half = len(bars) // 2
            raw_left  = sum(bars[:half])  / max(1, half)
            raw_right = sum(bars[half:])  / max(1, len(bars) - half)
        else:
            raw_left = raw_right = 0.0

        # CAVA reports 0-255 → map to 0-100 for the angle math
        raw_left  = max(0.0, min(raw_left  * 100.0 / 255.0, 100.0))
        raw_right = max(0.0, min(raw_right * 100.0 / 255.0, 100.0))

        self.left_smooth  = self.left_smooth  * self.EMA_PREV + raw_left  * self.EMA_CURR
        self.right_smooth = self.right_smooth * self.EMA_PREV + raw_right * self.EMA_CURR

        # ---- composite ----
        base = self.vu_background.copy()
        draw = ImageDraw.Draw(base)
        sw   = base.width

        # 1. Needles (under the text)
        for pivot, value in (
            (self.LEFT_PIVOT,  self.left_smooth),
            (self.RIGHT_PIVOT, self.right_smooth),
        ):
            tip = self._needle_tip(pivot, value)
            draw.line([pivot, tip], fill=self.NEEDLE_COLOR, width=self.NEEDLE_WIDTH)
            r = self.PIVOT_RADIUS
            draw.ellipse(
                [pivot[0] - r, pivot[1] - r, pivot[0] + r, pivot[1] + r],
                fill=self.NEEDLE_COLOR,
            )

        # 2. Artist + title (shadowed, scrolling if needed)
        state   = self.current_state or {}
        service = (state.get("service") or "").lower()
        if service == "webradio":
            artist = state.get("name",  "")
            title  = state.get("title", "")
        else:
            artist = state.get("artist", "")
            title  = state.get("title",  "")

        if artist:
            self.scroll_offset_artist = self._draw_scrolling_text(
                base, artist, self.font_artist, self.ARTIST_Y, sw,
                self.scroll_offset_artist, fill=self.FILL_ARTIST, with_shadow=True,
            )
        if title:
            self.scroll_offset_title = self._draw_scrolling_text(
                base, title, self.font_title, self.TITLE_Y, sw,
                self.scroll_offset_title, fill=self.FILL_TITLE, with_shadow=True,
            )

        # 3. Bottom info: vol X% | samplerate | bitdepth
        volume     = state.get("volume", "")
        samplerate = state.get("samplerate", "")
        bitdepth   = state.get("bitdepth", "")
        try:
            vol_str = f"vol {int(float(volume))}%"
        except Exception:
            vol_str = ""

        info_parts = [p for p in (vol_str, str(samplerate or ""), str(bitdepth or "")) if p]
        info_text  = " | ".join(info_parts)
        if info_text:
            w = self._measure(self.font_info, info_text)
            self._shadow_text(
                draw, ((sw - w) // 2, self.INFO_Y), info_text,
                self.font_info, fill=self.FILL_INFO,
            )

        # ---- push to OLED ----
        self.display_manager.oled.display(base.convert(self.display_manager.oled.mode))

    # ------------------------------------------------------------------
    #  Mode lifecycle
    # ------------------------------------------------------------------

    def start_mode(self):
        if self.mode_manager.get_mode() != self.mode_name:
            self.logger.warning("VUScreen: start_mode called outside vuscreen state.")
            return

        self.is_active        = True
        self.left_smooth      = 0.0
        self.right_smooth     = 0.0
        self.scroll_offset_artist = 0
        self.scroll_offset_title  = 0
        self.stop_event.clear()
        self.last_update_time = time.time()

        # Seed state so first frame has artist/title
        with self.state_lock:
            try:
                self.current_state = (
                    self.volumio_listener.get_current_state()
                    if self.volumio_listener else None
                )
            except Exception:
                self.current_state = None

        # Spectrum thread (only when CAVA is enabled in user prefs)
        if self.mode_manager.config.get("cava_enabled", False) and not self.running_spectrum:
            self.running_spectrum = True
            self.spectrum_thread  = threading.Thread(
                target=self._read_fifo, daemon=True, name="VUSpectrum"
            )
            self.spectrum_thread.start()

        # Update / render thread
        if not self.update_thread or not self.update_thread.is_alive():
            self.update_thread = threading.Thread(
                target=self._update_loop, daemon=True, name="VUUpdate"
            )
            self.update_thread.start()

        # Pull a fresh state so the first frame is current
        try:
            if self.volumio_listener and getattr(self.volumio_listener, "socketIO", None):
                self.volumio_listener.socketIO.emit("getState", {})
        except Exception as e:
            self.logger.debug(f"VUScreen: getState emit failed -> {e}")

        self.logger.info("VUScreen: started.")

    def stop_mode(self):
        if not self.is_active:
            return
        self.is_active = False

        self.running_spectrum = False
        if self.spectrum_thread and self.spectrum_thread.is_alive():
            self.spectrum_thread.join(timeout=1)

        self.stop_event.set()
        self.update_event.set()
        if self.update_thread and self.update_thread.is_alive():
            self.update_thread.join(timeout=1)

        self.display_manager.clear_screen()
        self.logger.info("VUScreen: stopped.")

    # ------------------------------------------------------------------
    #  External API used by main.py rotary handlers + CommandDispatcher
    # ------------------------------------------------------------------

    def adjust_volume(self, volume_change):
        if not self.volumio_listener:
            return
        try:
            if volume_change > 0:
                self.volumio_listener.socketIO.emit("volume", "+")
            elif volume_change < 0:
                self.volumio_listener.socketIO.emit("volume", "-")
        except Exception as e:
            self.logger.error(f"VUScreen: adjust_volume failed -> {e}")

    def display_playback_info(self):
        state = self.volumio_listener.get_current_state() if self.volumio_listener else None
        if state:
            with self.state_lock:
                self.current_state = state
            self._draw()

    def toggle_play_pause(self):
        if not self.volumio_listener or not self.volumio_listener.is_connected():
            return
        try:
            self.volumio_listener.socketIO.emit("toggle", {})
        except Exception as e:
            self.logger.error(f"VUScreen: toggle_play_pause failed -> {e}")
