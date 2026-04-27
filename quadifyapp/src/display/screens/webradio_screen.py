# src/display/screens/webradio_screen.py

import os
import logging
import threading
import time
from io import BytesIO

import requests
from PIL import Image, ImageDraw, ImageFont


class WebRadioScreen:
    """
    Webradio screen for Quadify.

    Visual design (256 x 64 OLED):

        +------------------------------------------------------------+ y=0
        | [LOGO]  Station Name (small, dim)                          |
        | [ 42 ]  Song Title (medium, scrolling if long)             |
        | [    ]  Artist (small, dim)                                |
        |------------------------------------------------------------| y=42
        | ▂▄▆█▆▄▂  (18 spectrum bars)        vol 80% | 128 kbps      |
        +------------------------------------------------------------+ y=64

    Data sources:
      - VolumioListener: state changes for service=webradio.
      - Quadify CAVA fifo at /tmp/display.fifo for the spectrum bars.
      - Station logo fetched on demand from the Volumio `albumart` URL,
        cached per-URL, fetched on a background thread so a slow HTTP
        round-trip never stalls a frame.

    Volumio's webradio metadata is famously inconsistent; this screen
    falls back gracefully:
      - station name: state['name']            -> state['service']  -> "WebRadio"
      - song title:   state['title']           -> ""
      - artist:       state['artist']          -> "" (often blank for radio)
    """

    # ----- layout (px) -----
    LOGO_X            = 2
    LOGO_Y            = 2
    LOGO_SIZE         = 42

    TEXT_X            = 50
    STATION_Y         = -1
    TITLE_Y           = 11
    ARTIST_Y          = 28

    DIVIDER_Y         = 42

    SPECTRUM_X        = 2
    SPECTRUM_BOTTOM   = 61          # bars grow upward from this baseline
    SPECTRUM_HEIGHT   = 16          # max bar height
    N_BARS            = 18
    BAR_W             = 6
    BAR_GAP           = 2

    INFO_X            = 158
    INFO_Y            = 50

    # ----- style -----
    FILL_TITLE        = (255, 255, 255)
    FILL_STATION      = (190, 190, 190)
    FILL_ARTIST       = (160, 160, 160)
    FILL_INFO         = (150, 150, 150)
    FILL_BAR          = (170, 170, 170)
    FILL_DIVIDER      = (60,  60,  60)

    SCROLL_PX         = 1
    SCROLL_GAP        = 30          # gap between repeats when scrolling

    EMA_PREV          = 0.55        # spectrum smoothing weight on previous
    EMA_CURR          = 0.45

    # ----- spectrum source -----
    FIFO_PATH         = "/tmp/display.fifo"

    def __init__(self, display_manager, volumio_listener, mode_manager):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(logging.INFO)

        self.display_manager  = display_manager
        self.volumio_listener = volumio_listener
        self.mode_manager     = mode_manager
        self.mode_name        = "webradio"

        # ----- fonts (config.yaml display.fonts keys) -----
        fonts = display_manager.fonts
        self.font_station = fonts.get("data_font",    ImageFont.load_default())
        self.font_title   = fonts.get("artist_font",  ImageFont.load_default())
        self.font_artist  = fonts.get("volume_small", ImageFont.load_default())
        self.font_info    = fonts.get("volume_small", ImageFont.load_default())

        # ----- state / threading -----
        self.is_active        = False
        self.latest_state     = None
        self.current_state    = None
        self.state_lock       = threading.Lock()
        self.update_event     = threading.Event()
        self.stop_event       = threading.Event()
        self.update_thread    = None

        # ----- spectrum -----
        self.spectrum_bars     = []
        self.smoothed_bars     = [0.0] * self.N_BARS
        self._spec_lock        = threading.Lock()
        self.spectrum_thread   = None
        self.running_spectrum  = False

        # ----- station logo cache -----
        # Logo fetch happens on a background thread; the draw loop reads
        # _logo_image while the fetcher writes it under _logo_lock.
        self._logo_lock        = threading.Lock()
        self._logo_url         = None
        self._logo_image       = None
        self._logo_pending_url = None

        # ----- scrolling marquee -----
        self.scroll_offset_title = 0

        if self.volumio_listener:
            self.volumio_listener.state_changed.connect(self.on_volumio_state_change)
        self.logger.info("WebRadioScreen initialised.")

    # ------------------------------------------------------------------
    #  Volumio state
    # ------------------------------------------------------------------

    def on_volumio_state_change(self, sender, state):
        if not self.is_active or self.mode_manager.get_mode() != self.mode_name:
            return
        if (state.get("service") or "").lower() != "webradio":
            return

        with self.state_lock:
            # Reset marquee on track change
            if self.current_state and (
                state.get("title")  != self.current_state.get("title") or
                state.get("artist") != self.current_state.get("artist") or
                state.get("name")   != self.current_state.get("name")
            ):
                self.scroll_offset_title = 0
            self.latest_state = state

        # Trigger a logo fetch if the albumart URL has changed.
        new_url = (state.get("albumart") or "").strip()
        if new_url and new_url != self._logo_url and new_url != self._logo_pending_url:
            self._logo_pending_url = new_url
            threading.Thread(
                target=self._fetch_logo_async, args=(new_url,),
                daemon=True, name="WebRadioLogoFetch",
            ).start()

        self.update_event.set()

    # ------------------------------------------------------------------
    #  Logo fetch (async, off the draw thread)
    # ------------------------------------------------------------------

    def _resolve_logo_url(self, url: str) -> str:
        if url.startswith(("http://", "https://")):
            return url
        host = getattr(self.volumio_listener, "host", "localhost") or "localhost"
        port = getattr(self.volumio_listener, "port", 3000) or 3000
        if not url.startswith("/"):
            url = "/" + url
        return f"http://{host}:{port}{url}"

    def _fetch_logo_async(self, url: str):
        full = self._resolve_logo_url(url)
        try:
            resp = requests.get(full, timeout=4)
            resp.raise_for_status()
            img = Image.open(BytesIO(resp.content))
            if img.mode == "RGBA":
                bg = Image.new("RGB", img.size, (0, 0, 0))
                bg.paste(img, mask=img.split()[3])
                img = bg
            else:
                img = img.convert("RGB")
            img = img.resize((self.LOGO_SIZE, self.LOGO_SIZE), Image.LANCZOS)
            with self._logo_lock:
                # Only commit if this is still the most recently requested URL
                if url == self._logo_pending_url:
                    self._logo_image = img
                    self._logo_url   = url
        except Exception as e:
            self.logger.warning(f"WebRadioScreen: logo fetch failed ({full}): {e}")
        finally:
            if url == self._logo_pending_url:
                self._logo_pending_url = None
            self.update_event.set()

    # ------------------------------------------------------------------
    #  CAVA spectrum reader
    # ------------------------------------------------------------------

    def _read_fifo(self):
        retry_delay = 1.0
        self.logger.info(f"WebRadioScreen: spectrum reader started -> {self.FIFO_PATH}")
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
                self.logger.error(f"WebRadioScreen: FIFO read error -> {e}")
                time.sleep(retry_delay)
        self.logger.info("WebRadioScreen: spectrum reader exiting.")

    @staticmethod
    def _resample(bars, n):
        """Sample CAVA's variable bar count down/up to N evenly-spaced bars."""
        if not bars:
            return [0] * n
        if len(bars) == n:
            return list(bars)
        step = len(bars) / n
        return [bars[min(len(bars) - 1, int(i * step))] for i in range(n)]

    # ------------------------------------------------------------------
    #  Update loop (~30 fps for smooth spectrum)
    # ------------------------------------------------------------------

    def _update_loop(self):
        self.logger.info("WebRadioScreen: update loop started.")
        while not self.stop_event.is_set():
            triggered = self.update_event.wait(timeout=0.033)  # ~30 fps tick
            with self.state_lock:
                if triggered and self.latest_state:
                    self.current_state = self.latest_state.copy()
                    self.latest_state  = None
                    self.update_event.clear()

            if (
                self.is_active
                and self.mode_manager.get_mode() == self.mode_name
                and self.current_state
            ):
                self._draw()
        self.logger.info("WebRadioScreen: update loop exiting.")

    # ------------------------------------------------------------------
    #  Mode lifecycle
    # ------------------------------------------------------------------

    def start_mode(self):
        if self.mode_manager.get_mode() != self.mode_name:
            self.logger.warning("WebRadioScreen: start_mode called outside webradio.")
            return

        self.is_active = True
        self.scroll_offset_title = 0
        self.smoothed_bars = [0.0] * self.N_BARS
        self.stop_event.clear()

        # Seed state for first frame
        with self.state_lock:
            try:
                self.current_state = (
                    self.volumio_listener.get_current_state()
                    if self.volumio_listener else None
                )
            except Exception:
                self.current_state = None

        # If the seed state already has an albumart URL, kick off the fetch
        if self.current_state:
            url = (self.current_state.get("albumart") or "").strip()
            if url and url != self._logo_url:
                self._logo_pending_url = url
                threading.Thread(
                    target=self._fetch_logo_async, args=(url,),
                    daemon=True, name="WebRadioLogoFetch",
                ).start()

        # Spectrum reader
        if self.mode_manager.config.get("cava_enabled", False) and not self.running_spectrum:
            self.running_spectrum = True
            self.spectrum_thread = threading.Thread(
                target=self._read_fifo, daemon=True, name="WebRadioSpectrum",
            )
            self.spectrum_thread.start()

        # Update / render thread
        if self.update_thread is None or not self.update_thread.is_alive():
            self.update_thread = threading.Thread(
                target=self._update_loop, daemon=True, name="WebRadioUpdate",
            )
            self.update_thread.start()

        # Force a fresh state pull
        try:
            if self.volumio_listener and getattr(self.volumio_listener, "socketIO", None):
                self.volumio_listener.socketIO.emit("getState", {})
        except Exception as e:
            self.logger.debug(f"WebRadioScreen: getState emit failed: {e}")

        self.logger.info("WebRadioScreen: started.")

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
        self.logger.info("WebRadioScreen: stopped.")

    # ------------------------------------------------------------------
    #  Draw helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _measure(font, text):
        try:
            return int(font.getlength(text))
        except AttributeError:
            bbox = font.getbbox(text)
            return (bbox[2] - bbox[0]) if bbox else 0

    def _draw_scrolling_text(self, base_image, text, font, x, y, clip_w,
                             scroll_offset, fill):
        """Centre-fit if it fits, marquee-scroll if it doesn't."""
        if not text:
            return 0
        text_w = self._measure(font, text)
        if text_w <= clip_w:
            ImageDraw.Draw(base_image).text((x, y), text, font=font, fill=fill)
            return 0

        cycle      = text_w + self.SCROLL_GAP
        new_offset = (scroll_offset + self.SCROLL_PX) % cycle

        try:
            line_h = font.getbbox("Ay")[3]
        except Exception:
            line_h = 14
        # Crop existing region so the rest of the canvas shows through.
        y_clip = max(0, y)
        h_clip = min(line_h + 2, base_image.height - y_clip)
        if h_clip <= 0:
            return new_offset
        region = base_image.crop((x, y_clip, x + clip_w, y_clip + h_clip))
        rdraw  = ImageDraw.Draw(region)
        ty     = y - y_clip
        for rep in range(2):
            tx = -int(new_offset) + rep * cycle
            if tx + text_w < 0 or tx >= clip_w:
                continue
            rdraw.text((tx, ty), text, font=font, fill=fill)
        base_image.paste(region, (x, y_clip))
        return new_offset

    def _draw_logo(self, base_image):
        with self._logo_lock:
            logo = self._logo_image
        if logo is None:
            # Placeholder: a bordered square so the layout doesn't collapse
            # while we're waiting for the logo to download.
            d = ImageDraw.Draw(base_image)
            d.rectangle(
                [self.LOGO_X, self.LOGO_Y,
                 self.LOGO_X + self.LOGO_SIZE - 1, self.LOGO_Y + self.LOGO_SIZE - 1],
                outline=self.FILL_DIVIDER, width=1,
            )
            return
        base_image.paste(logo, (self.LOGO_X, self.LOGO_Y))

    def _draw_spectrum(self, base_image):
        with self._spec_lock:
            bars = list(self.spectrum_bars)
        if not bars:
            return

        sampled = self._resample(bars, self.N_BARS)
        # CAVA range is 0-255; normalise to 0-1, EMA-smooth.
        for i, v in enumerate(sampled):
            t = max(0.0, min(v / 255.0, 1.0))
            self.smoothed_bars[i] = (
                self.smoothed_bars[i] * self.EMA_PREV + t * self.EMA_CURR
            )

        d = ImageDraw.Draw(base_image)
        x = self.SPECTRUM_X
        bottom = self.SPECTRUM_BOTTOM
        for v in self.smoothed_bars:
            h = int(v * self.SPECTRUM_HEIGHT)
            if h > 0:
                d.rectangle(
                    [x, bottom - h, x + self.BAR_W - 1, bottom],
                    fill=self.FILL_BAR,
                )
            x += self.BAR_W + self.BAR_GAP

    # ------------------------------------------------------------------
    #  Main draw
    # ------------------------------------------------------------------

    def _draw(self):
        oled = self.display_manager.oled
        if not oled:
            return

        base = Image.new("RGB", oled.size, "black")
        sw, sh = oled.size

        # 1. Logo
        self._draw_logo(base)

        # 2. Text column
        state = self.current_state or {}
        station = (state.get("name") or state.get("service") or "WebRadio").strip()
        title   = (state.get("title")  or "").strip()
        artist  = (state.get("artist") or "").strip()

        text_clip_w = sw - self.TEXT_X - 2
        d = ImageDraw.Draw(base)

        if station:
            d.text((self.TEXT_X, self.STATION_Y), station[:40],
                   font=self.font_station, fill=self.FILL_STATION)

        if title:
            self.scroll_offset_title = self._draw_scrolling_text(
                base, title, self.font_title,
                self.TEXT_X, self.TITLE_Y, text_clip_w,
                self.scroll_offset_title, self.FILL_TITLE,
            )

        if artist:
            d.text((self.TEXT_X, self.ARTIST_Y), artist[:40],
                   font=self.font_artist, fill=self.FILL_ARTIST)

        # 3. Divider
        d.line(
            [(self.SPECTRUM_X, self.DIVIDER_Y), (sw - 4, self.DIVIDER_Y)],
            fill=self.FILL_DIVIDER, width=1,
        )

        # 4. Spectrum
        self._draw_spectrum(base)

        # 5. Bottom info: vol + bitrate
        volume   = state.get("volume", "")
        bitrate  = state.get("bitrate", "")
        try:
            vol_str = f"vol {int(float(volume))}%"
        except Exception:
            vol_str = ""
        info_parts = [p for p in (vol_str, str(bitrate or "")) if p]
        info_text  = " | ".join(info_parts)
        if info_text:
            d.text((self.INFO_X, self.INFO_Y), info_text,
                   font=self.font_info, fill=self.FILL_INFO)

        # 6. Push to OLED
        self.display_manager.oled.display(base.convert(self.display_manager.oled.mode))

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
            self.logger.error(f"WebRadioScreen: adjust_volume failed -> {e}")

    def display_radioplayback_info(self):
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
            self.logger.error(f"WebRadioScreen: toggle_play_pause failed -> {e}")
