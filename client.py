#!/usr/bin/env python3
"""
Remote Support Client Agent
============================
Runs on the machine requesting support. Captures the screen and sends
frames to the relay server, then executes mouse/keyboard commands
received from the operator.

Usage:
    python client.py [--server ws://localhost:3000] [--fps 10] [--quality 60]
"""

import argparse
import asyncio
import io
import json
import platform
import signal
import sys
import threading
import time

try:
    import websockets
except ImportError:
    sys.exit("Missing dependency: pip install websockets")

try:
    import mss
    import mss.tools
except ImportError:
    sys.exit("Missing dependency: pip install mss")

try:
    from PIL import Image
except ImportError:
    sys.exit("Missing dependency: pip install Pillow")

try:
    import pyautogui

    pyautogui.FAILSAFE = False  # Allow moving to corners
    pyautogui.PAUSE = 0  # No delay between actions
except ImportError:
    sys.exit("Missing dependency: pip install pyautogui")


# ─── Configuration ────────────────────────────────────────────────────────────

DEFAULT_SERVER = "ws://localhost:3000"
DEFAULT_FPS = 10
DEFAULT_QUALITY = 50
MAX_DIMENSION = 1920  # Max width/height for captured frames


# ─── Input Handler ────────────────────────────────────────────────────────────

class InputHandler:
    """Translates operator input events into local pyautogui actions."""

    # Map JS key names → pyautogui key names
    KEY_MAP = {
        "Enter": "enter", "Backspace": "backspace", "Tab": "tab",
        "Escape": "escape", "Delete": "delete", "Insert": "insert",
        "Home": "home", "End": "end", "PageUp": "pageup", "PageDown": "pagedown",
        "ArrowUp": "up", "ArrowDown": "down", "ArrowLeft": "left", "ArrowRight": "right",
        "Control": "ctrl", "Shift": "shift", "Alt": "alt", "Meta": "win",
        "CapsLock": "capslock", "NumLock": "numlock", "ScrollLock": "scrolllock",
        "F1": "f1", "F2": "f2", "F3": "f3", "F4": "f4", "F5": "f5", "F6": "f6",
        "F7": "f7", "F8": "f8", "F9": "f9", "F10": "f10", "F11": "f11", "F12": "f12",
        " ": "space",
    }

    MOUSE_BUTTON_MAP = {
        0: "left", 1: "middle", 2: "right",
    }

    def __init__(self, screen_width, screen_height):
        self.screen_width = screen_width
        self.screen_height = screen_height

    def handle(self, msg):
        """Dispatch an input event message."""
        t = msg.get("type")
        try:
            if t == "mouse_move":
                self._mouse_move(msg)
            elif t == "mouse_click":
                self._mouse_click(msg)
            elif t == "mouse_double_click":
                self._mouse_double_click(msg)
            elif t == "mouse_scroll":
                self._mouse_scroll(msg)
            elif t == "key_press":
                self._key_press(msg)
            elif t == "key_combo":
                self._key_combo(msg)
        except Exception as e:
            print(f"  [!] Input error ({t}): {e}")

    def _scale_coords(self, x_ratio, y_ratio):
        """Convert 0‑1 ratios to absolute screen coords."""
        return int(x_ratio * self.screen_width), int(y_ratio * self.screen_height)

    def _mouse_move(self, msg):
        x, y = self._scale_coords(msg["x"], msg["y"])
        pyautogui.moveTo(x, y, _pause=False)

    def _mouse_click(self, msg):
        x, y = self._scale_coords(msg["x"], msg["y"])
        btn = self.MOUSE_BUTTON_MAP.get(msg.get("button", 0), "left")
        pyautogui.click(x, y, button=btn, _pause=False)

    def _mouse_double_click(self, msg):
        x, y = self._scale_coords(msg["x"], msg["y"])
        btn = self.MOUSE_BUTTON_MAP.get(msg.get("button", 0), "left")
        pyautogui.doubleClick(x, y, button=btn, _pause=False)

    def _mouse_scroll(self, msg):
        x, y = self._scale_coords(msg["x"], msg["y"])
        clicks = msg.get("delta", 0)
        pyautogui.scroll(clicks, x, y, _pause=False)

    def _key_press(self, msg):
        key = msg.get("key", "")
        mapped = self.KEY_MAP.get(key, key.lower() if len(key) == 1 else key)
        pyautogui.press(mapped, _pause=False)

    def _key_combo(self, msg):
        keys = msg.get("keys", [])
        mapped = [self.KEY_MAP.get(k, k.lower() if len(k) == 1 else k) for k in keys]
        pyautogui.hotkey(*mapped, _pause=False)


# ─── Screen Capturer ─────────────────────────────────────────────────────────

class ScreenCapturer:
    """Captures the primary monitor and returns JPEG bytes."""

    def __init__(self, quality=DEFAULT_QUALITY, max_dim=MAX_DIMENSION):
        self.quality = quality
        self.max_dim = max_dim
        self.sct = mss.mss()
        self.monitor = self.sct.monitors[1]  # Primary monitor

    @property
    def width(self):
        return self.monitor["width"]

    @property
    def height(self):
        return self.monitor["height"]

    def capture(self) -> bytes:
        """Take a screenshot and return compressed JPEG bytes."""
        shot = self.sct.grab(self.monitor)
        img = Image.frombytes("RGB", (shot.width, shot.height), shot.rgb)

        # Resize if too large
        w, h = img.size
        if w > self.max_dim or h > self.max_dim:
            ratio = min(self.max_dim / w, self.max_dim / h)
            img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=self.quality, optimize=True)
        return buf.getvalue()


# ─── Main Client ─────────────────────────────────────────────────────────────

class RemoteSupportClient:
    def __init__(self, server_url, fps, quality):
        self.server_url = server_url
        self.fps = fps
        self.capturer = ScreenCapturer(quality=quality)
        self.input_handler = InputHandler(self.capturer.width, self.capturer.height)
        self.ws = None
        self.session_id = None
        self.pin = None
        self.connected = False
        self.operator_connected = False
        self.running = True

    async def run(self):
        print(f"\n{'='*50}")
        print(f"  Remote Support Client")
        print(f"  Screen: {self.capturer.width}x{self.capturer.height}")
        print(f"  Server: {self.server_url}")
        print(f"  FPS: {self.fps}  Quality: {self.capturer.quality}%")
        print(f"{'='*50}\n")

        while self.running:
            try:
                async with websockets.connect(
                    self.server_url,
                    max_size=10 * 1024 * 1024,  # 10 MB
                    ping_interval=20,
                    ping_timeout=60,
                ) as ws:
                    self.ws = ws
                    self.connected = True
                    await self._register()
                    await self._main_loop()
            except websockets.exceptions.ConnectionClosed:
                print("[!] Connection closed, reconnecting in 3s...")
            except ConnectionRefusedError:
                print(f"[!] Cannot connect to {self.server_url}, retrying in 3s...")
            except Exception as e:
                print(f"[!] Error: {e}, retrying in 3s...")

            self.connected = False
            self.operator_connected = False
            if self.running:
                await asyncio.sleep(3)

    async def _register(self):
        """Register with the relay server."""
        info = {
            "hostname": platform.node(),
            "os": f"{platform.system()} {platform.release()}",
            "screen": f"{self.capturer.width}x{self.capturer.height}",
        }
        await self.ws.send(json.dumps({
            "type": "client_register",
            "clientInfo": info,
        }))

    async def _main_loop(self):
        """Concurrently send frames and receive input."""
        send_task = asyncio.create_task(self._send_frames())
        recv_task = asyncio.create_task(self._receive_messages())
        try:
            await asyncio.gather(send_task, recv_task)
        except Exception:
            send_task.cancel()
            recv_task.cancel()

    async def _send_frames(self):
        """Capture and send screen frames at the configured FPS."""
        interval = 1.0 / self.fps
        while self.running and self.connected:
            if self.operator_connected:
                try:
                    t0 = time.monotonic()
                    frame = await asyncio.to_thread(self.capturer.capture)
                    await self.ws.send(frame)
                    elapsed = time.monotonic() - t0
                    sleep_time = max(0, interval - elapsed)
                    await asyncio.sleep(sleep_time)
                except Exception as e:
                    if self.running:
                        print(f"[!] Frame send error: {e}")
                    break
            else:
                await asyncio.sleep(0.5)

    async def _receive_messages(self):
        """Receive and handle control messages from the server."""
        async for raw in self.ws:
            if isinstance(raw, bytes):
                continue
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            t = msg.get("type")

            if t == "registered":
                self.session_id = msg["sessionId"]
                self.pin = msg["pin"]
                print(f"  ✓ Registered!")
                print(f"  ┌─────────────────────────────┐")
                print(f"  │  Support PIN:  {self.pin}        │")
                print(f"  └─────────────────────────────┘")
                print(f"  Share this PIN with your support operator.\n")

                # Send screen info
                await self.ws.send(json.dumps({
                    "type": "screen_info",
                    "width": self.capturer.width,
                    "height": self.capturer.height,
                }))

            elif t == "operator_connected":
                self.operator_connected = True
                print("  ✓ Operator connected! Sharing screen...")

            elif t == "operator_disconnected":
                self.operator_connected = False
                print("  ✗ Operator disconnected. Waiting for reconnect...")

            elif t in ("mouse_move", "mouse_click", "mouse_double_click",
                       "mouse_scroll", "key_press", "key_combo"):
                self.input_handler.handle(msg)

            elif t == "client_disconnected":
                print("  Session ended by server.")
                self.running = False
                break

    def stop(self):
        self.running = False


# ─── Entry Point ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Remote Support Client Agent")
    parser.add_argument("--server", default=DEFAULT_SERVER, help=f"WebSocket server URL (default: {DEFAULT_SERVER})")
    parser.add_argument("--fps", type=int, default=DEFAULT_FPS, help=f"Frames per second (default: {DEFAULT_FPS})")
    parser.add_argument("--quality", type=int, default=DEFAULT_QUALITY, help=f"JPEG quality 1-100 (default: {DEFAULT_QUALITY})")
    args = parser.parse_args()

    client = RemoteSupportClient(args.server, args.fps, args.quality)

    def handle_signal(*_):
        print("\n[!] Shutting down...")
        client.stop()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    asyncio.run(client.run())


if __name__ == "__main__":
    main()
