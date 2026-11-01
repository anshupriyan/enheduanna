"""
IGI (𒅆) — Global Windows Hotkey Listener
Triggers IGI screen freeze when Ctrl+Shift+Q (or configured hotkey) is pressed from any application.
"""

from __future__ import annotations

import threading
from typing import Callable, Optional

try:
    from pynput import keyboard
except ImportError:
    keyboard = None


class GlobalHotkeyManager:
    """Listens for global key combination in a non-blocking background thread."""

    def __init__(self, hotkey_str: str = "<ctrl>+<shift>+q", on_trigger: Optional[Callable[[], None]] = None):
        self.hotkey_str = hotkey_str
        self.on_trigger = on_trigger
        self._listener: Optional[keyboard.GlobalHotKeys] = None
        self._thread: Optional[threading.Thread] = None

    def start(self):
        """Start listening for the global hotkey."""
        if not keyboard:
            print("[IGI Hotkey] Warning: pynput not loaded. Hotkey listener inactive.")
            return

        def _run():
            try:
                hotkeys = {
                    self.hotkey_str: self._handle_trigger
                }
                with keyboard.GlobalHotKeys(hotkeys) as self._listener:
                    self._listener.join()
            except Exception as e:
                print(f"[IGI Hotkey] Error in listener: {e}")

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()

    def _handle_trigger(self):
        if self.on_trigger:
            self.on_trigger()

    def stop(self):
        """Stop listening."""
        if self._listener:
            try:
                self._listener.stop()
            except Exception:
                pass

