#!/usr/bin/env python3
"""
Remote Support Client — Windows Edition
=========================================
Standalone GUI client that captures the screen and relays it to the
support server. An operator can then view the screen and control
mouse/keyboard remotely.

Designed to be compiled with PyInstaller into a single .exe.
"""

import argparse
import asyncio
import ctypes
import io
import json
import os
import platform
import signal
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox

import websockets
import mss
import mss.tools
from PIL import Image
import pyautogui

pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0


# ── Windows DPI awareness ────────────────────────────────────────────────────
if sys.platform == "win32":
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # Per-monitor DPI aware
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════════════
#  Input Handler
# ═══════════════════════════════════════════════════════════════════════════════

class InputHandler:
    """Translates operator input events into local pyautogui actions."""

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

    MOUSE_BUTTON_MAP = {0: "left", 1: "middle", 2: "right"}

    def __init__(self, screen_width, screen_height):
        self.screen_width = screen_width
        self.screen_height = screen_height

    def handle(self, msg):
        t = msg.get("type")
        try:
            if t == "mouse_move":
                x, y = self._scale(msg["x"], msg["y"])
                pyautogui.moveTo(x, y, _pause=False)
            elif t == "mouse_click":
                x, y = self._scale(msg["x"], msg["y"])
                btn = self.MOUSE_BUTTON_MAP.get(msg.get("button", 0), "left")
                pyautogui.click(x, y, button=btn, _pause=False)
            elif t == "mouse_double_click":
                x, y = self._scale(msg["x"], msg["y"])
                btn = self.MOUSE_BUTTON_MAP.get(msg.get("button", 0), "left")
                pyautogui.doubleClick(x, y, button=btn, _pause=False)
            elif t == "mouse_scroll":
                x, y = self._scale(msg["x"], msg["y"])
                pyautogui.scroll(msg.get("delta", 0), x, y, _pause=False)
            elif t == "key_press":
                key = msg.get("key", "")
                mapped = self.KEY_MAP.get(key, key.lower() if len(key) == 1 else key)
                pyautogui.press(mapped, _pause=False)
            elif t == "key_combo":
                keys = msg.get("keys", [])
                mapped = [self.KEY_MAP.get(k, k.lower() if len(k) == 1 else k) for k in keys]
                pyautogui.hotkey(*mapped, _pause=False)
        except Exception as e:
            print(f"  [!] Input error ({t}): {e}")

    def _scale(self, x_ratio, y_ratio):
        return int(x_ratio * self.screen_width), int(y_ratio * self.screen_height)


# ═══════════════════════════════════════════════════════════════════════════════
#  Screen Capturer
# ═══════════════════════════════════════════════════════════════════════════════

class ScreenCapturer:
    MAX_DIM = 1920

    def __init__(self, quality=50):
        self.quality = quality
        self.sct = mss.mss()
        self.monitor = self.sct.monitors[1]

    @property
    def width(self):
        return self.monitor["width"]

    @property
    def height(self):
        return self.monitor["height"]

    def capture(self) -> bytes:
        shot = self.sct.grab(self.monitor)
        img = Image.frombytes("RGB", (shot.width, shot.height), shot.rgb)
        w, h = img.size
        if w > self.MAX_DIM or h > self.MAX_DIM:
            ratio = min(self.MAX_DIM / w, self.MAX_DIM / h)
            img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=self.quality, optimize=True)
        return buf.getvalue()


# ═══════════════════════════════════════════════════════════════════════════════
#  Network Client (runs in background thread)
# ═══════════════════════════════════════════════════════════════════════════════

class NetworkClient:
    def __init__(self, server_url, fps, quality, callbacks):
        self.server_url = server_url
        self.fps = fps
        self.capturer = ScreenCapturer(quality=quality)
        self.input_handler = InputHandler(self.capturer.width, self.capturer.height)
        self.callbacks = callbacks  # dict of callback functions
        self.ws = None
        self.session_id = None
        self.pin = None
        self.operator_connected = False
        self.running = True
        self._loop = None

    def start(self):
        """Start the network client in a background thread."""
        thread = threading.Thread(target=self._run_loop, daemon=True)
        thread.start()

    def _run_loop(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._connect_loop())

    async def _connect_loop(self):
        while self.running:
            try:
                self.callbacks.get("on_status", lambda s, m: None)("connecting", "Connecting...")
                async with websockets.connect(
                    self.server_url,
                    max_size=10 * 1024 * 1024,
                    ping_interval=20,
                    ping_timeout=60,
                ) as ws:
                    self.ws = ws
                    await self._register()
                    await self._main_loop()
            except websockets.exceptions.ConnectionClosed:
                self.callbacks.get("on_status", lambda s, m: None)("error", "Connection lost, reconnecting...")
            except ConnectionRefusedError:
                self.callbacks.get("on_status", lambda s, m: None)("error", f"Cannot reach server, retrying...")
            except Exception as e:
                self.callbacks.get("on_status", lambda s, m: None)("error", f"Error: {e}")

            self.operator_connected = False
            if self.running:
                await asyncio.sleep(3)

    async def _register(self):
        info = {
            "hostname": platform.node(),
            "os": f"{platform.system()} {platform.release()}",
            "screen": f"{self.capturer.width}x{self.capturer.height}",
        }
        await self.ws.send(json.dumps({"type": "client_register", "clientInfo": info}))

    async def _main_loop(self):
        send_task = asyncio.create_task(self._send_frames())
        recv_task = asyncio.create_task(self._receive_messages())
        try:
            await asyncio.gather(send_task, recv_task)
        except Exception:
            send_task.cancel()
            recv_task.cancel()

    async def _send_frames(self):
        interval = 1.0 / self.fps
        while self.running:
            if self.operator_connected:
                try:
                    t0 = time.monotonic()
                    frame = await asyncio.to_thread(self.capturer.capture)
                    await self.ws.send(frame)
                    elapsed = time.monotonic() - t0
                    await asyncio.sleep(max(0, interval - elapsed))
                except Exception:
                    break
            else:
                await asyncio.sleep(0.5)

    async def _receive_messages(self):
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
                self.callbacks.get("on_registered", lambda p: None)(self.pin)
                self.callbacks.get("on_status", lambda s, m: None)("waiting", "Waiting for operator...")
                await self.ws.send(json.dumps({
                    "type": "screen_info",
                    "width": self.capturer.width,
                    "height": self.capturer.height,
                }))

            elif t == "operator_connected":
                self.operator_connected = True
                self.callbacks.get("on_status", lambda s, m: None)("connected", "Operator connected — sharing screen")
                self.callbacks.get("on_operator", lambda c: None)(True)

            elif t == "operator_disconnected":
                self.operator_connected = False
                self.callbacks.get("on_status", lambda s, m: None)("waiting", "Operator disconnected, waiting...")
                self.callbacks.get("on_operator", lambda c: None)(False)

            elif t in ("mouse_move", "mouse_click", "mouse_double_click",
                        "mouse_scroll", "key_press", "key_combo"):
                self.input_handler.handle(msg)

    def stop(self):
        self.running = False


# ═══════════════════════════════════════════════════════════════════════════════
#  GUI Application
# ═══════════════════════════════════════════════════════════════════════════════

class RemoteSupportApp:
    WINDOW_WIDTH = 420
    WINDOW_HEIGHT = 380

    # Color palette
    BG          = "#0f1420"
    BG_CARD     = "#181f30"
    BG_INPUT    = "#111827"
    BORDER      = "#263049"
    TEXT        = "#e2e8f0"
    TEXT_DIM    = "#6b7fa0"
    ACCENT      = "#3b82f6"
    GREEN       = "#22c55e"
    RED         = "#ef4444"
    YELLOW      = "#f59e0b"

    def __init__(self, server_url, fps, quality):
        self.server_url = server_url
        self.fps = fps
        self.quality = quality
        self.pin = None
        self.client = None

        self.root = tk.Tk()
        self.root.title("Remote Support")
        self.root.geometry(f"{self.WINDOW_WIDTH}x{self.WINDOW_HEIGHT}")
        self.root.resizable(False, False)
        self.root.configure(bg=self.BG)
        self.root.protocol("WM_DELETE_CLOSE", self._on_close)

        # Try to set icon
        try:
            if sys.platform == "win32":
                icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.ico")
                if os.path.exists(icon_path):
                    self.root.iconbitmap(icon_path)
        except Exception:
            pass

        self._build_ui()
        self._start_client()

    def _build_ui(self):
        root = self.root

        # ── Title bar area ──
        title_frame = tk.Frame(root, bg=self.BG)
        title_frame.pack(fill="x", padx=24, pady=(24, 0))

        tk.Label(
            title_frame, text="🖥  Remote Support", font=("Segoe UI", 16, "bold"),
            bg=self.BG, fg=self.TEXT, anchor="w"
        ).pack(side="left")

        # ── Status indicator ──
        self.status_frame = tk.Frame(root, bg=self.BG)
        self.status_frame.pack(fill="x", padx=24, pady=(6, 0))

        self.status_dot = tk.Canvas(self.status_frame, width=10, height=10, bg=self.BG, highlightthickness=0)
        self.status_dot.pack(side="left", padx=(0, 6))
        self._dot_id = self.status_dot.create_oval(1, 1, 9, 9, fill=self.TEXT_DIM, outline="")

        self.status_label = tk.Label(
            self.status_frame, text="Initializing...",
            font=("Segoe UI", 10), bg=self.BG, fg=self.TEXT_DIM, anchor="w"
        )
        self.status_label.pack(side="left")

        # ── PIN Card ──
        pin_card = tk.Frame(root, bg=self.BG_CARD, highlightbackground=self.BORDER, highlightthickness=1)
        pin_card.pack(fill="x", padx=24, pady=(20, 0))

        tk.Label(
            pin_card, text="YOUR SUPPORT PIN", font=("Segoe UI", 9, "bold"),
            bg=self.BG_CARD, fg=self.TEXT_DIM
        ).pack(pady=(16, 4))

        self.pin_label = tk.Label(
            pin_card, text="------", font=("Consolas", 36, "bold"),
            bg=self.BG_CARD, fg=self.ACCENT, cursor="hand2"
        )
        self.pin_label.pack(pady=(0, 4))
        self.pin_label.bind("<Button-1>", self._copy_pin)

        self.pin_hint = tk.Label(
            pin_card, text="Click PIN to copy to clipboard",
            font=("Segoe UI", 9), bg=self.BG_CARD, fg=self.TEXT_DIM
        )
        self.pin_hint.pack(pady=(0, 16))

        # ── Info section ──
        info_frame = tk.Frame(root, bg=self.BG)
        info_frame.pack(fill="x", padx=24, pady=(20, 0))

        tk.Label(
            info_frame, text="Share this PIN with your support operator.",
            font=("Segoe UI", 10), bg=self.BG, fg=self.TEXT, wraplength=360, justify="center"
        ).pack()

        tk.Label(
            info_frame,
            text="They will be able to see your screen and\ncontrol your mouse and keyboard.",
            font=("Segoe UI", 9), bg=self.BG, fg=self.TEXT_DIM, justify="center"
        ).pack(pady=(6, 0))

        # ── Server info ──
        server_frame = tk.Frame(root, bg=self.BG)
        server_frame.pack(fill="x", padx=24, pady=(16, 0))

        tk.Label(
            server_frame, text=f"Server: {self.server_url}",
            font=("Consolas", 9), bg=self.BG, fg=self.TEXT_DIM
        ).pack()

        # ── Disconnect button ──
        btn_frame = tk.Frame(root, bg=self.BG)
        btn_frame.pack(fill="x", padx=24, pady=(16, 24))

        self.disconnect_btn = tk.Button(
            btn_frame, text="Disconnect & Exit", font=("Segoe UI", 10),
            bg="#1e293b", fg=self.RED, activebackground="#2d3a4f",
            activeforeground=self.RED, relief="flat", bd=0,
            cursor="hand2", padx=16, pady=8, command=self._on_close
        )
        self.disconnect_btn.pack(fill="x")

    def _start_client(self):
        callbacks = {
            "on_registered": self._on_registered,
            "on_status": self._on_status,
            "on_operator": self._on_operator,
        }
        self.client = NetworkClient(self.server_url, self.fps, self.quality, callbacks)
        self.client.start()

    def _on_registered(self, pin):
        self.pin = pin
        self.root.after(0, lambda: self.pin_label.configure(text=pin))

    def _on_status(self, state, message):
        def update():
            self.status_label.configure(text=message)
            colors = {
                "connecting": self.YELLOW,
                "waiting": self.YELLOW,
                "connected": self.GREEN,
                "error": self.RED,
            }
            color = colors.get(state, self.TEXT_DIM)
            self.status_dot.itemconfig(self._dot_id, fill=color)
        self.root.after(0, update)

    def _on_operator(self, connected):
        def update():
            if connected:
                self.pin_label.configure(fg=self.GREEN)
                self.pin_hint.configure(text="Operator is controlling your machine")
            else:
                self.pin_label.configure(fg=self.ACCENT)
                self.pin_hint.configure(text="Click PIN to copy to clipboard")
        self.root.after(0, update)

    def _copy_pin(self, _event=None):
        if self.pin:
            self.root.clipboard_clear()
            self.root.clipboard_append(self.pin)
            self.pin_hint.configure(text="✓ PIN copied!", fg=self.GREEN)
            self.root.after(2000, lambda: self.pin_hint.configure(
                text="Click PIN to copy to clipboard", fg=self.TEXT_DIM
            ))

    def _on_close(self):
        if self.client:
            self.client.stop()
        self.root.destroy()

    def run(self):
        # Center window on screen
        self.root.update_idletasks()
        x = (self.root.winfo_screenwidth() // 2) - (self.WINDOW_WIDTH // 2)
        y = (self.root.winfo_screenheight() // 2) - (self.WINDOW_HEIGHT // 2)
        self.root.geometry(f"+{x}+{y}")

        # Keep window on top initially
        self.root.attributes("-topmost", True)
        self.root.after(3000, lambda: self.root.attributes("-topmost", False))

        self.root.mainloop()


# ═══════════════════════════════════════════════════════════════════════════════
#  Entry Point
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Remote Support Client (Windows)")
    parser.add_argument("--server", default="ws://localhost:3000",
                        help="WebSocket server URL (default: ws://localhost:3000)")
    parser.add_argument("--fps", type=int, default=10,
                        help="Frames per second (default: 10)")
    parser.add_argument("--quality", type=int, default=50,
                        help="JPEG quality 1-100 (default: 50)")
    parser.add_argument("--no-gui", action="store_true",
                        help="Run in console mode (no GUI window)")
    args = parser.parse_args()

    if args.no_gui:
        # Fallback console mode
        from client import RemoteSupportClient
        client = RemoteSupportClient(args.server, args.fps, args.quality)
        signal.signal(signal.SIGINT, lambda *_: client.stop())
        asyncio.run(client.run())
    else:
        app = RemoteSupportApp(args.server, args.fps, args.quality)
        app.run()


if __name__ == "__main__":
    main()
