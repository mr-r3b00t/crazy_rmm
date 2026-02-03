# Remote Support — Client/Server

A lightweight remote support tool that lets a user request help and an operator take control of their mouse, keyboard, and see their screen in real time.

## Architecture

```
┌──────────────┐       WebSocket        ┌──────────────┐
│   Client     │◄──────────────────────►│   Server     │
│  (Python)    │   frames + input cmds  │  (Node.js)   │
│              │                        │              │
│ • Screen cap │                        │ • Session    │
│ • Input exec │                        │   management │
└──────────────┘                        │ • Relay      │
                                        └──────┬───────┘
                                               │ WebSocket
                                               ▼
                                        ┌──────────────┐
                                        │  Operator    │
                                        │  (Browser)   │
                                        │              │
                                        │ • Screen view│
                                        │ • Input send │
                                        └──────────────┘
```

### Components

| Component | Technology | Role |
|-----------|-----------|------|
| **Server** | Node.js + Express + ws | Session management, WebSocket relay |
| **Client Agent** | Python + mss + pyautogui | Screen capture, input execution |
| **Operator Console** | Browser (HTML/JS) | View screen, send mouse/keyboard |

## Quick Start

### 1. Server Setup

```bash
cd remote-support
npm install
npm start
```

The server starts on port 3000 by default. Set `PORT` env var to change.

### 2. Client Setup (on the machine needing support)

```bash
pip install websockets mss Pillow pyautogui
python client.py --server ws://SERVER_IP:3000
```

The client will display a **6-digit PIN**. Share this with the operator.

#### Client Options

| Flag | Default | Description |
|------|---------|-------------|
| `--server` | `ws://localhost:3000` | Server WebSocket URL |
| `--fps` | `10` | Frames per second (1–30) |
| `--quality` | `50` | JPEG quality 1–100 |

Higher FPS and quality use more bandwidth. Recommended: 8–15 fps, quality 40–60.

### 3. Operator (in a browser)

Open `http://SERVER_IP:3000/operator.html`

- Enter the client's **PIN** and click Connect
- Or click a waiting session in the sidebar

## Features

- **Screen Streaming** — JPEG frame capture sent via WebSocket binary frames
- **Remote Mouse** — Move, click, double-click, right-click, scroll
- **Remote Keyboard** — Key presses, modifier combos (Ctrl+C, etc.)
- **PIN-based Sessions** — 6-digit PIN for easy connection
- **Toggle Control** — Operator can switch between control and view-only mode
- **Ctrl+Alt+Del** — Special key combo button
- **Fullscreen** — Expand the viewer to fill the screen
- **Auto-reconnect** — Both client and operator reconnect on disconnect
- **Session List** — Operators see all waiting sessions in real-time

## Security Considerations

This is a proof-of-concept. For production use, add:

- **TLS/SSL** — Run behind a reverse proxy (nginx) with HTTPS/WSS
- **Authentication** — Add operator login with password/tokens
- **PIN Expiry** — Auto-expire PINs after a timeout
- **Rate Limiting** — Prevent brute-force PIN guessing
- **Encryption** — Encrypt frame data end-to-end
- **Audit Logging** — Log all sessions and actions
- **Consent UI** — Show a clear prompt on the client machine before sharing

## Platform Notes

### Client (Python)

- **Linux**: May need `sudo apt install python3-tk python3-dev` for pyautogui
- **macOS**: Grant accessibility permissions in System Preferences → Privacy → Accessibility
- **Windows**: Works out of the box

### Network

The server must be reachable from both the client and operator. For remote use:
- Deploy the server on a VPS/cloud instance
- Use a reverse proxy with SSL for WSS support
- Open port 3000 (or your configured port)

## Folder Structure

```
remote-support/
├── server.js           # Node.js relay server
├── client.py           # Python client agent
├── package.json        # Node dependencies
├── requirements.txt    # Python dependencies
├── README.md           # This file
└── public/
    ├── index.html      # Landing page
    └── operator.html   # Operator web console
```

## License

MIT
