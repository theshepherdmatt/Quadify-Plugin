"""
Boot orchestration & command dispatch for Quadify.

Splits two concerns out of main.py:
  * CommandDispatcher / start_command_server: single-bind UNIX socket server
    with a swappable target (boot phase vs. live ModeManager). Replaces the
    old "early server hands off to real server" dance.
  * BootCoordinator: shows splash, waits for first Volumio state OR timeout
    OR explicit skip. No fixed minimum loading time, no ready-loop, no
    manual interrupt.
  * is_network_ready / is_clock_synced / wait_for_trustworthy_clock: small
    helpers used between splash and clock so the clock is never shown with a
    wrong time on a cold boot — the boot placeholder is held until NTP has
    synced (or playback takes over).
"""

import logging
import os
import socket
import subprocess
import threading
import time
from datetime import datetime
from typing import Callable, Optional


# --------------------------- Network / clock readiness ---------------------------

def is_network_ready() -> bool:
    """True iff the system has at least one default IPv4 route."""
    try:
        out = subprocess.run(
            ["ip", "route", "show", "default"],
            capture_output=True, text=True, timeout=2,
        )
        return "default via" in out.stdout
    except Exception:
        return False


def is_clock_synced() -> bool:
    """True iff the system clock is trustworthy.

    This Volumio image syncs time with ntpd (ntpsec), NOT systemd-timesyncd, and
    on a no-RTC Pi the kernel `NTPSynchronized` flag is unreliable (it can read
    'yes' before the clock has actually been corrected). So we ask ntpd directly:
    `ntpq -c 'rv 0 leap'` reports `leap=00` only once ntpd has selected a peer
    and disciplined the clock; before that it reports `leap=11` (alarm). A
    year >= 2024 check stays as a backstop against a 1970/way-past boot.

    Fast path: ntpd is conservative and can take ~5 min to declare leap=00,
    which left the "Connecting to network" placeholder on screen far too long.
    quadify-timesync.service does a one-shot SNTP step early in boot and drops a
    marker once the clock is verified against a real network source; we trust
    that immediately rather than wait for ntpd's slow formal sync.
    """
    # Backstop: a clock stuck in the past (RTC-less Pi pre-NTP) is never real.
    if datetime.now().year < 2024:
        return False
    # Fast path: our one-shot SNTP step verified real time this boot. The marker
    # lives in /run (tmpfs) so it's cleared every boot and only exists after a
    # confirmed sync — trust it without waiting for ntpd's slow leap=00.
    try:
        if os.path.exists("/run/quadify-timesynced"):
            return True
    except Exception:
        pass
    # Authoritative: ask ntpd whether it has actually synchronised.
    try:
        out = subprocess.run(
            ["ntpq", "-c", "rv 0 leap"],
            capture_output=True, text=True, timeout=2,
        )
        if "leap=00" in out.stdout:
            return True
        if "leap=" in out.stdout:          # leap=11/01/10 → not synced yet
            return False
    except Exception:
        pass
    # Fallback if ntpq is unavailable: kernel NTP flag (best-effort).
    try:
        out = subprocess.run(
            ["timedatectl", "show", "-p", "NTPSynchronized", "--value"],
            capture_output=True, text=True, timeout=2,
        )
        return out.stdout.strip().lower() == "yes"
    except Exception:
        return False


def wait_for_trustworthy_clock(mode_manager,
                               poll_interval: float = 0.5,
                               logger: Optional[logging.Logger] = None) -> str:
    """Hold on the boot placeholder until it's safe to show the clock.

    Returns when EITHER:
      * the system clock becomes trustworthy   -> returns "synced"
        (the caller may now enter the clock screen), OR
      * something routes us off the 'boot' mode -> returns "left_boot"
        (a play-state arrived and ModeManager switched to a playback screen;
        the caller must NOT enter the clock).

    By design there is NO timeout: an offline unit that never reaches NTP keeps
    the placeholder (network.png) on screen indefinitely rather than show a
    wrong time. It polls in short sleeps, so the socketio listener thread — and
    any playback screen it starts via process_state_change — keep running
    unhindered while we wait.
    """
    log = logger or logging.getLogger("BootReady")
    log.info("Holding boot placeholder until the system clock is trustworthy…")
    saw_net = False
    while True:
        # Playback precedence: ModeManager auto-routes a play-state off 'boot'
        # on the socketio thread. If that happened, leave the clock alone —
        # playback now owns the screen and doesn't depend on the time.
        if mode_manager.get_mode() != "boot":
            log.info("Routed off boot during clock wait (playback took over); not showing clock.")
            return "left_boot"
        if not saw_net and is_network_ready():
            saw_net = True
            log.info("Network ready (default route present); waiting for NTP sync…")
        if is_clock_synced():
            log.info("System clock trustworthy; entering clock.")
            return "synced"
        time.sleep(poll_interval)


_STREAMING_MODES = (
    "streaming", "tidal", "qobuz", "spotify",
    "radioparadise", "motherearthradio",
)
_LIST_MODES = (
    "library", "albums", "artists", "genres",
    "last100", "mediaservers", "favourites", "playlists",
)
_PLAYBACK_TO_SCREEN_ATTR = {
    "original":        "original_screen",
    "modern":          "modern_screen",
    "minimal":         "minimal_screen",
    "vuscreen":        "vu_screen",
    "digitalvuscreen": "digitalvu_screen",
}


# --------------------------- IR / IPC dispatch ---------------------------

class CommandDispatcher:
    """
    Routes textual commands (from IR daemon, IPC clients, etc.) to ModeManager.

    Until `attach_mode_manager()` is called, the only commands that do anything
    are `shutdown` and the "press anything" keys (menu/select/ok/toggle/back),
    which fire `on_skip_splash` so the user can shortcut the boot splash.
    """

    def __init__(self, volumio_listener, on_skip_splash: Callable[[], None]):
        self.logger = logging.getLogger("CommandDispatcher")
        self.volumio_listener = volumio_listener
        self._on_skip_splash = on_skip_splash
        self._mode_manager = None

    def attach_mode_manager(self, mode_manager) -> None:
        self._mode_manager = mode_manager

    def dispatch(self, command: str) -> None:
        cmd = (command or "").strip()
        if not cmd:
            return

        if cmd == "shutdown":
            subprocess.run(
                ["sudo", "/bin/systemctl", "poweroff", "--no-wall"],
                check=False,
            )
            return

        if self._mode_manager is None:
            if cmd in ("menu", "select", "ok", "toggle", "back"):
                self.logger.info("Skip splash via command: %s", cmd)
                self._on_skip_splash()
            return

        mm = self._mode_manager
        current = mm.get_mode()

        if cmd == "home":
            mm.trigger("to_clock")
        elif cmd == "menu":
            if current == "clock":
                mm.trigger("to_menu")
        elif cmd == "toggle":
            mm.toggle_play_pause()
        elif cmd == "select":
            self._handle_select(mm, current)
        elif cmd in ("scroll_up", "scroll_left"):
            self._handle_scroll(mm, current, -1)
        elif cmd in ("scroll_down", "scroll_right"):
            self._handle_scroll(mm, current, +1)
        elif cmd == "seek_plus":
            subprocess.run(["volumio", "seek", "plus"], check=False)
        elif cmd == "seek_minus":
            subprocess.run(["volumio", "seek", "minus"], check=False)
        elif cmd == "skip_next":
            subprocess.run(["volumio", "next"], check=False)
        elif cmd == "skip_previous":
            subprocess.run(["volumio", "previous"], check=False)
        elif cmd == "volume_plus":
            self.volumio_listener.increase_volume()
        elif cmd == "volume_minus":
            self.volumio_listener.decrease_volume()
        elif cmd == "back":
            mm.trigger("back")
        elif cmd == "repeat":
            pass
        else:
            self.logger.debug("Unknown command: %s", cmd)

    @staticmethod
    def _handle_scroll(mm, current_mode, direction: int) -> None:
        if current_mode == "menu":
            mm.menu_manager.scroll_selection(direction)
        elif current_mode == "configmenu":
            mm.config_menu.scroll_selection(direction)
        elif current_mode == "clockmenu":
            mm.clock_menu.scroll_selection(direction)
        elif current_mode == "screensavermenu":
            mm.screensaver_menu.scroll_selection(direction)
        elif current_mode == "radio":
            mm.radio_manager.scroll_selection(direction)
        elif current_mode in _LIST_MODES:
            mm.library_manager.scroll_selection(direction)
        elif current_mode in _STREAMING_MODES:
            mm.streaming_manager.scroll_selection(direction)
        elif current_mode == "screensaver":
            mm.exit_screensaver()
        elif current_mode == "sleep":
            mm.wake_from_sleep()

    @staticmethod
    def _handle_select(mm, current_mode) -> None:
        if current_mode == "menu":
            mm.menu_manager.select_item(); return
        if current_mode == "configmenu":
            mm.config_menu.select_item(); return
        if current_mode == "screensavermenu":
            mm.screensaver_menu.select_item(); return
        if current_mode == "clockmenu":
            mm.clock_menu.select_item(); return
        if current_mode in _LIST_MODES:
            mm.library_manager.select_item(); return
        if current_mode in _STREAMING_MODES:
            mm.streaming_manager.select_item(); return
        if current_mode == "radio":
            mm.radio_manager.select_item(); return
        if current_mode in _PLAYBACK_TO_SCREEN_ATTR:
            screen = getattr(mm, _PLAYBACK_TO_SCREEN_ATTR[current_mode], None)
            if screen:
                screen.toggle_play_pause()
            return
        if current_mode == "clock":
            mm.trigger("to_menu"); return
        if current_mode == "screensaver":
            mm.exit_screensaver(); return
        if current_mode == "sleep":
            mm.wake_from_sleep(); return


# --------------------------- IPC server ---------------------------

def start_command_server(dispatcher: CommandDispatcher,
                         sock_path: str = "/tmp/quadify.sock") -> threading.Thread:
    """
    Bind once, run for the lifetime of the process. The only thing that ever
    changes about behaviour is the dispatcher's internal target.
    """
    log = logging.getLogger("CommandServer")

    def _serve():
        try:
            os.unlink(sock_path)
        except FileNotFoundError:
            pass
        except OSError:
            pass

        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(sock_path)
        try:
            os.chmod(sock_path, 0o666)
        except OSError:
            pass
        srv.listen(5)
        log.info("Quadify command server listening on %s", sock_path)

        try:
            while True:
                conn, _ = srv.accept()
                try:
                    with conn:
                        data = conn.recv(1024)
                        if not data:
                            continue
                        cmd = data.decode("utf-8", errors="replace")
                        log.debug("Recv: %s", cmd.strip())
                        dispatcher.dispatch(cmd)
                except Exception as e:
                    log.warning("Connection handler error: %s", e)
        except Exception as e:
            log.error("Server loop terminated: %s", e)
        finally:
            try:
                srv.close()
            except Exception:
                pass
            try:
                os.unlink(sock_path)
            except OSError:
                pass

    t = threading.Thread(target=_serve, daemon=True, name="CommandServer")
    t.start()
    return t


# --------------------------- Boot coordination ---------------------------

class BootCoordinator:
    """
    Splash → live-UI handoff. No timers for the sake of timers.

    Flow:
      1. Render the static splash logo (one frame, returns immediately).
      2. Subscribe to the first Volumio pushState event.
      3. wait_for_handoff() blocks until ANY of:
           * first state arrives,
           * `max_wait` seconds pass,
           * `skip()` is called (e.g. user pressed a button).
         Returns {"reason": str, "state": dict|None}.

    The caller drives the actual mode transition after this returns; for
    `play` states ModeManager's own state_changed handler will already have
    routed to the playback screen by then in the common case.
    """

    def __init__(self, display_manager, volumio_listener,
                 logo_path: Optional[str], max_wait: float = 4.0):
        self.logger = logging.getLogger("BootCoordinator")
        self.display_manager = display_manager
        self.volumio_listener = volumio_listener
        self.logo_path = logo_path
        self.max_wait = max_wait

        self._exit_event = threading.Event()
        self._exit_reason: Optional[str] = None
        self._first_state: Optional[dict] = None
        self._connected = False
        self._lock = threading.Lock()

    def show_splash(self) -> None:
        if not self.logo_path:
            self.logger.debug("No logo configured; skipping splash render.")
            return
        try:
            self.display_manager.display_image(self.logo_path)
        except Exception as e:
            self.logger.error("Splash render failed: %s", e)

    def attach(self) -> None:
        """Subscribe to pushState. Idempotent."""
        if self._connected:
            return
        self.volumio_listener.state_changed.connect(self._on_first_state)
        self._connected = True

    def detach(self) -> None:
        if not self._connected:
            return
        try:
            self.volumio_listener.state_changed.disconnect(self._on_first_state)
        except Exception:
            pass
        self._connected = False

    def _on_first_state(self, sender, state, **kwargs):
        with self._lock:
            if self._exit_event.is_set():
                return
            self._first_state = dict(state) if isinstance(state, dict) else None
            self._exit_reason = "state"
        self._exit_event.set()

    def skip(self) -> None:
        with self._lock:
            if self._exit_event.is_set():
                return
            self._exit_reason = "skip"
        self._exit_event.set()

    def wait_for_handoff(self) -> dict:
        """Block until exit condition. Returns {'reason', 'state'}."""
        # Race safety: if the listener buffered a state before we attached,
        # treat that as the first state.
        if not self._exit_event.is_set():
            try:
                buffered = self.volumio_listener.get_current_state()
            except Exception:
                buffered = None
            if buffered:
                with self._lock:
                    if not self._exit_event.is_set():
                        self._first_state = dict(buffered)
                        self._exit_reason = "state"
                self._exit_event.set()

        fired = self._exit_event.wait(timeout=self.max_wait)
        if not fired and self._exit_reason is None:
            self._exit_reason = "timeout"
        self.detach()
        return {"reason": self._exit_reason, "state": self._first_state}
