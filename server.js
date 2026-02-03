const express = require("express");
const http = require("http");
const WebSocket = require("ws");
const { v4: uuidv4 } = require("uuid");
const path = require("path");

const app = express();
const server = http.createServer(app);
const wss = new WebSocket.Server({ server });

app.use(express.static(path.join(__dirname, "public")));
app.use(express.json());

// ─── Session Store ───────────────────────────────────────────────────────────

const sessions = new Map();
// session: { id, pin, clientWs, operatorWs, clientInfo, createdAt, status }

function generatePin() {
  return String(Math.floor(100000 + Math.random() * 900000));
}

function broadcastSessionList() {
  const list = [];
  for (const [id, s] of sessions) {
    if (s.status === "waiting") {
      list.push({
        id: s.id,
        pin: s.pin,
        clientInfo: s.clientInfo,
        createdAt: s.createdAt,
      });
    }
  }
  wss.clients.forEach((ws) => {
    if (ws.role === "operator" && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "session_list", sessions: list }));
    }
  });
}

// ─── REST Endpoints ──────────────────────────────────────────────────────────

app.get("/api/sessions", (_req, res) => {
  const list = [];
  for (const [_id, s] of sessions) {
    list.push({
      id: s.id,
      pin: s.pin,
      clientInfo: s.clientInfo,
      createdAt: s.createdAt,
      status: s.status,
    });
  }
  res.json(list);
});

// ─── WebSocket Handling ──────────────────────────────────────────────────────

wss.on("connection", (ws) => {
  ws.isAlive = true;
  ws.on("pong", () => (ws.isAlive = true));

  ws.on("message", (raw) => {
    let msg;
    try {
      // Handle binary frames (screenshot data from client)
      if (Buffer.isBuffer(raw) || raw instanceof ArrayBuffer) {
        if (ws.role === "client" && ws.sessionId) {
          const session = sessions.get(ws.sessionId);
          if (session && session.operatorWs && session.operatorWs.readyState === WebSocket.OPEN) {
            session.operatorWs.send(raw);
          }
        }
        return;
      }
      msg = JSON.parse(raw.toString());
    } catch {
      return;
    }

    switch (msg.type) {
      // ── Client registers for support ──
      case "client_register": {
        const id = uuidv4();
        const pin = generatePin();
        const session = {
          id,
          pin,
          clientWs: ws,
          operatorWs: null,
          clientInfo: msg.clientInfo || {},
          createdAt: new Date().toISOString(),
          status: "waiting",
        };
        sessions.set(id, session);
        ws.role = "client";
        ws.sessionId = id;
        ws.send(
          JSON.stringify({
            type: "registered",
            sessionId: id,
            pin,
          })
        );
        broadcastSessionList();
        console.log(`[+] Client registered: session=${id} pin=${pin}`);
        break;
      }

      // ── Operator joins ──
      case "operator_join": {
        ws.role = "operator";
        broadcastSessionList();
        console.log("[+] Operator connected");
        break;
      }

      // ── Operator connects to a session by PIN ──
      case "operator_connect": {
        const target = [...sessions.values()].find(
          (s) => s.pin === msg.pin && s.status === "waiting"
        );
        if (!target) {
          ws.send(JSON.stringify({ type: "error", message: "Invalid PIN or session not available" }));
          return;
        }
        target.operatorWs = ws;
        target.status = "connected";
        ws.sessionId = target.id;
        ws.send(
          JSON.stringify({
            type: "connected",
            sessionId: target.id,
            clientInfo: target.clientInfo,
          })
        );
        if (target.clientWs && target.clientWs.readyState === WebSocket.OPEN) {
          target.clientWs.send(
            JSON.stringify({ type: "operator_connected" })
          );
        }
        broadcastSessionList();
        console.log(`[→] Operator connected to session ${target.id}`);
        break;
      }

      // ── Input events from operator → client ──
      case "mouse_move":
      case "mouse_click":
      case "mouse_double_click":
      case "mouse_scroll":
      case "key_press":
      case "key_release":
      case "key_combo": {
        if (ws.sessionId) {
          const session = sessions.get(ws.sessionId);
          if (session && session.clientWs && session.clientWs.readyState === WebSocket.OPEN) {
            session.clientWs.send(JSON.stringify(msg));
          }
        }
        break;
      }

      // ── Client sends screen metadata ──
      case "screen_info": {
        if (ws.sessionId) {
          const session = sessions.get(ws.sessionId);
          if (session && session.operatorWs && session.operatorWs.readyState === WebSocket.OPEN) {
            session.operatorWs.send(JSON.stringify(msg));
          }
        }
        break;
      }

      // ── Disconnect ──
      case "disconnect": {
        handleDisconnect(ws);
        break;
      }

      // ── Client settings update ──
      case "client_settings": {
        if (ws.sessionId) {
          const session = sessions.get(ws.sessionId);
          if (session) {
            session.clientInfo = { ...session.clientInfo, ...msg.settings };
          }
        }
        break;
      }
    }
  });

  ws.on("close", () => handleDisconnect(ws));
  ws.on("error", () => handleDisconnect(ws));
});

function handleDisconnect(ws) {
  if (ws.sessionId) {
    const session = sessions.get(ws.sessionId);
    if (session) {
      if (ws.role === "client") {
        if (session.operatorWs && session.operatorWs.readyState === WebSocket.OPEN) {
          session.operatorWs.send(JSON.stringify({ type: "client_disconnected" }));
          session.operatorWs.sessionId = null;
        }
        sessions.delete(ws.sessionId);
        console.log(`[-] Client disconnected, session ${ws.sessionId} removed`);
      } else if (ws.role === "operator") {
        session.operatorWs = null;
        session.status = "waiting";
        if (session.clientWs && session.clientWs.readyState === WebSocket.OPEN) {
          session.clientWs.send(JSON.stringify({ type: "operator_disconnected" }));
        }
        console.log(`[-] Operator disconnected from session ${ws.sessionId}`);
      }
      broadcastSessionList();
    }
  }
}

// ─── Heartbeat ───────────────────────────────────────────────────────────────

const interval = setInterval(() => {
  wss.clients.forEach((ws) => {
    if (!ws.isAlive) return ws.terminate();
    ws.isAlive = false;
    ws.ping();
  });
}, 30000);
wss.on("close", () => clearInterval(interval));

// ─── Start ───────────────────────────────────────────────────────────────────

const PORT = process.env.PORT || 3000;
server.listen(PORT, () => {
  console.log(`\n╔══════════════════════════════════════════════╗`);
  console.log(`║       Remote Support Server v1.0.0            ║`);
  console.log(`╠══════════════════════════════════════════════╣`);
  console.log(`║  Server:    http://localhost:${PORT}             ║`);
  console.log(`║  Operator:  http://localhost:${PORT}/operator    ║`);
  console.log(`╚══════════════════════════════════════════════╝\n`);
});
