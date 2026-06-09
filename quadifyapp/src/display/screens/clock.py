import os
import time
import threading
from PIL import Image, ImageDraw

from startup import is_clock_synced


class Clock:
    def __init__(self, display_manager, config, volumio_listener):
        self.display_manager = display_manager
        self.volumio_listener = volumio_listener
        self.config = config
        self.running = False
        self.thread = None

        # Time-trust gate: never paint a pre-sync (e.g. 1970) time. Latches
        # True once the system clock is NTP-synced, after which we stop
        # checking; until then render_clock_image() returns a placeholder.
        self._time_trusted = False
        self._waiting_img = None

        self.font_y_offsets = {
            "clock_sans":    -15,
            "clock_dots":    -10,
            "clock_digital":   0,
            "clock_bold":     -5
        }
        self.font_line_spacing = {
            "clock_sans":    15,
            "clock_dots":    10,
            "clock_digital":  8,
            "clock_bold":    12
        }
        self.date_font_map = {
            "clock_sans":    "clockdate_sans",
            "clock_dots":    "clockdate_dots",
            "clock_digital": "clockdate_digital",
            "clock_bold":    "clockdate_bold"
        }

    def render_clock_image(self, offset_x=0):
        """Create a PIL image of the current clock (with optional horizontal offset).

        Until the system clock is trustworthy (NTP-synced), this returns a
        neutral placeholder instead of the time, so NO caller — the update
        loop, transitions, or any to_clock() route (incl. the pause/stop
        timer) — can paint a wrong, pre-sync time. Gating here covers every
        render path in one place.
        """
        if not self._time_trustworthy():
            return self._waiting_image(
                self.display_manager.oled.width,
                self.display_manager.oled.height,
                offset_x,
            )
        time_font_key = self.config.get("clock_font_key", "clock_digital")
        if time_font_key not in self.display_manager.fonts:
            time_font_key = "clock_digital"
        date_font_key = self.date_font_map.get(time_font_key, "clockdate_digital")
        show_seconds = self.config.get("show_seconds", False)
        time_str = time.strftime("%H:%M:%S") if show_seconds else time.strftime("%H:%M")
        show_date = self.config.get("show_date", False)
        date_str = time.strftime("%d %b %Y") if show_date else None

        y_offset = self.font_y_offsets.get(time_font_key, 0)
        line_gap = self.font_line_spacing.get(time_font_key, 10)
        w = self.display_manager.oled.width
        h = self.display_manager.oled.height

        img = Image.new("RGB", (w, h), "black")
        draw = ImageDraw.Draw(img)
        time_font = self.display_manager.fonts[time_font_key]
        date_font = self.display_manager.fonts.get(date_font_key, time_font)

        lines = []
        if time_str:
            lines.append((time_str, time_font))
        if date_str:
            lines.append((date_str, date_font))

        # Compute layout
        total_height = 0
        line_dims = []
        for (text, font) in lines:
            box = draw.textbbox((0, 0), text, font=font)
            lw = box[2] - box[0]
            lh = box[3] - box[1]
            line_dims.append((lw, lh, font))
            total_height += lh
        if len(lines) == 2:
            total_height += line_gap

        start_y = (h - total_height) // 2 + y_offset
        y_cursor = start_y
        for i, (text, font) in enumerate(lines):
            lw, lh, the_font = line_dims[i]
            x_pos = (w - lw) // 2 + offset_x
            draw.text((x_pos, y_cursor), text, font=the_font, fill="white")
            y_cursor += lh
            if i < len(lines) - 1:
                y_cursor += line_gap

        return img

    def _time_trustworthy(self):
        """Latch True once the system clock is NTP-synced; never re-check after.
        Avoids spawning timedatectl every second for the process lifetime, and
        guarantees the clock never renders a pre-sync (e.g. 1970) time."""
        if self._time_trusted:
            return True
        if is_clock_synced():
            self._time_trusted = True
            print("Clock: system time trustworthy; rendering live time.")
        return self._time_trusted

    def _placeholder_path(self):
        """Resolve the boot 'getting ready' image: network.png beside the logo,
        else the logo itself. Returns None if neither is configured/present."""
        dm = self.display_manager
        logo = dm._dget("logo_path") if hasattr(dm, "_dget") else None
        if not logo:
            return None
        net = os.path.join(os.path.dirname(logo), "network.png")
        if os.path.isfile(net):
            return net
        return logo if os.path.isfile(logo) else None

    def _waiting_image(self, w, h, offset_x=0):
        """Placeholder shown until the clock is trustworthy (keeps the boot
        'getting ready' image on screen instead of a wrong time). Built once
        and cached; falls back to a blank frame if no image is available."""
        if self._waiting_img is None:
            base = Image.new("RGB", (w, h), "black")
            path = self._placeholder_path()
            if path:
                try:
                    ph = Image.open(path)
                    if ph.mode == "RGBA":
                        bg = Image.new("RGB", ph.size, (0, 0, 0))
                        bg.paste(ph, mask=ph.split()[3])
                        ph = bg
                    else:
                        ph = ph.convert("RGB")
                    if ph.size != (w, h):
                        ph = ph.resize((w, h), Image.LANCZOS)
                    base = ph
                except Exception:
                    pass
            self._waiting_img = base
        if offset_x:
            shifted = Image.new("RGB", (w, h), "black")
            shifted.paste(self._waiting_img, (offset_x, 0))
            return shifted
        return self._waiting_img

    def draw_clock(self, offset_x=0):
        """Draw the clock at a specified horizontal offset (for animation)."""
        img = self.render_clock_image(offset_x)
        final_img = img.convert(self.display_manager.oled.mode)
        self.display_manager.oled.display(final_img)

    def start(self):
        """Start continuous clock updates."""
        if not self.running:
            self.running = True
            self.thread = threading.Thread(target=self.update_clock, daemon=True)
            self.thread.start()
            print("Clock: Started.")

    def stop(self):
        """Stop continuous clock updates and clear the display."""
        if self.running:
            self.running = False
            self.thread.join()
            self.display_manager.clear_screen()
            print("Clock: Stopped.")

    def update_clock(self):
        """Threaded loop: updates the clock display every second."""
        while self.running:
            self.draw_clock()
            time.sleep(1)

    def toggle_play_pause(self):
        """Send toggle command to Volumio (if connected)."""
        if not self.volumio_listener or not self.volumio_listener.is_connected():
            return
        try:
            self.volumio_listener.socketIO.emit("toggle", {})
        except Exception as e:
            print(f"ClockScreen: toggle_play_pause failed => {e}")

    def slide_out_left(self, duration=0.5, fps=30):
        """Animate the clock sliding out left (for transitions)."""
        w = self.display_manager.oled.width
        frames = int(duration * fps)
        for step in range(frames + 1):
            offset = -int((w * step) / frames)
            self.draw_clock(offset_x=offset)
            time.sleep(duration / frames)

    def render_to_image(self, offset_x=0):
        """Render the clock to an image (for transition blending)."""
        return self.render_clock_image(offset_x)
