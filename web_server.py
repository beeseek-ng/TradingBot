"""
ForexBot Web Server, Health Dashboard & Live Log Streaming
===========================================================
Lightweight HTTP server designed for Heroku Web Dynos and cloud monitoring.
Provides real-time system status, uptime, account health, open positions,
and interactive streaming live logs at '/live-log'.
"""

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import parse_qs, urlparse

logger = logging.getLogger("ForexBot.Web")

# Log file path
BASE_DIR = Path(__file__).resolve().parent
LOG_FILE_PATH = BASE_DIR / "logs" / "bot_activity.log"

# Global state shared across the bot and web monitor
BOT_STATUS: Dict[str, Any] = {
    "status": "INITIALIZING",
    "mode": os.getenv("EXECUTION_MODE", os.getenv("BOT_MODE", "LIVE")).upper(),
    "start_time": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
    "account": {
        "login": os.getenv("MT5_ACCOUNT") or os.getenv("MT5_LOGIN", "5055872290"),
        "server": os.getenv("MT5_SERVER", "MetaQuotes-Demo"),
        "balance": 10000.0,
        "equity": 10000.0,
        "daily_drawdown_pct": 0.0,
    },
    "active_symbols": ["EURUSD", "GBPUSD", "XAUUSD"],
    "open_positions": [],
    "last_signal": None,
    "last_update": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
}


def update_web_status(
    status: str = None,
    mode: str = None,
    balance: float = None,
    equity: float = None,
    daily_dd_pct: float = None,
    open_positions: list = None,
    last_signal: dict = None,
) -> None:
    """Safely updates global state displayed on the web dashboard."""
    if status is not None:
        BOT_STATUS["status"] = status
    if mode is not None:
        BOT_STATUS["mode"] = mode.upper()
    if balance is not None:
        BOT_STATUS["account"]["balance"] = balance
    if equity is not None:
        BOT_STATUS["account"]["equity"] = equity
    if daily_dd_pct is not None:
        BOT_STATUS["account"]["daily_drawdown_pct"] = daily_dd_pct
    if open_positions is not None:
        BOT_STATUS["open_positions"] = open_positions
    if last_signal is not None:
        BOT_STATUS["last_signal"] = last_signal
    BOT_STATUS["last_update"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def get_recent_logs(max_lines: int = 250) -> List[str]:
    """Reads the last N lines safely from the bot log file."""
    if not LOG_FILE_PATH.exists():
        return [f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}] [INFO] Waiting for bot activity logs..."]
    
    try:
        with open(LOG_FILE_PATH, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
            return [line.rstrip("\r\n") for line in lines[-max_lines:]]
    except Exception as ex:
        return [f"[ERROR] Could not read log file: {ex}"]


class BotDashboardHandler(BaseHTTPRequestHandler):
    """HTTP request handler for status dashboard, health API, and live log stream."""

    def log_message(self, format, *args):
        # Suppress standard HTTP access logging to keep console clean
        pass

    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        # 1. Health JSON API
        if path in ["/health", "/healthz", "/status"]:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(BOT_STATUS, indent=2).encode("utf-8"))
            return

        # 2. Raw / JSON Logs API Endpoint (/api/logs)
        if path in ["/api/logs", "/logs.json"]:
            lines_param = int(query.get("lines", [250])[0])
            logs = get_recent_logs(max_lines=min(lines_param, 1000))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            resp = {
                "count": len(logs),
                "last_update": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
                "logs": logs
            }
            self.wfile.write(json.dumps(resp).encode("utf-8"))
            return

        # 3. Live Log Interactive Streaming Viewer (/live-log or /logs)
        if path in ["/live-log", "/live-logs", "/logs"]:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(self._render_live_log_page().encode("utf-8"))
            return

        # 4. Main HTML Dashboard (/)
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(self._render_dashboard_page().encode("utf-8"))

    def _render_dashboard_page(self) -> str:
        status_color = "#10b981" if BOT_STATUS["status"] == "RUNNING" else "#f59e0b"
        positions_rows = ""
        if BOT_STATUS["open_positions"]:
            for pos in BOT_STATUS["open_positions"]:
                pos_type = "BUY" if pos.get("type", 0) == 0 else "SELL"
                color = "#10b981" if pos_type == "BUY" else "#ef4444"
                positions_rows += f"""
                <tr>
                    <td>#{pos.get('ticket', 'N/A')}</td>
                    <td><strong>{pos.get('symbol', 'N/A')}</strong></td>
                    <td style="color:{color}; font-weight:bold;">{pos_type}</td>
                    <td>{pos.get('volume', 0.0)} lots</td>
                    <td>{pos.get('price_open', 0.0)}</td>
                    <td>{pos.get('sl', 'N/A')}</td>
                    <td>{pos.get('tp', 'N/A')}</td>
                </tr>
                """
        else:
            positions_rows = '<tr><td colspan="7" style="text-align:center; color:#9ca3af;">No open positions at this moment. Monitoring M15 candles...</td></tr>'

        signal_info = "Waiting for next session setup..."
        if BOT_STATUS["last_signal"]:
            sig = BOT_STATUS["last_signal"]
            signal_info = f"{sig.get('symbol')} {sig.get('type')} @ {sig.get('price')} ({sig.get('reason')})"

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ForexBot Cloud Live Dashboard</title>
    <meta http-equiv="refresh" content="10">
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; font-family: 'Inter', sans-serif; }}
        body {{ background: #0f172a; color: #f8fafc; padding: 24px; }}
        .container {{ max-width: 1000px; margin: 0 auto; }}
        .header {{ display: flex; justify-content: space-between; align-items: center; padding-bottom: 20px; border-bottom: 1px solid #334155; }}
        .header-actions {{ display: flex; gap: 10px; align-items: center; }}
        .btn {{ padding: 8px 16px; border-radius: 8px; font-size: 13px; font-weight: 600; text-decoration: none; display: inline-flex; align-items: center; gap: 6px; transition: all 0.2s; }}
        .btn-primary {{ background: #3b82f6; color: #ffffff; border: 1px solid #60a5fa; }}
        .btn-primary:hover {{ background: #2563eb; transform: translateY(-1px); }}
        .badge {{ padding: 6px 14px; border-radius: 9999px; font-weight: 600; font-size: 14px; background: {status_color}22; color: {status_color}; border: 1px solid {status_color}; }}
        .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 16px; margin: 24px 0; }}
        .card {{ background: #1e293b; border: 1px solid #334155; border-radius: 12px; padding: 20px; }}
        .card h3 {{ font-size: 13px; text-transform: uppercase; color: #94a3b8; letter-spacing: 0.05em; margin-bottom: 8px; }}
        .card .value {{ font-size: 24px; font-weight: 700; color: #f1f5f9; }}
        .table-card {{ background: #1e293b; border: 1px solid #334155; border-radius: 12px; padding: 20px; margin-top: 24px; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 12px; }}
        th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #334155; font-size: 14px; }}
        th {{ color: #94a3b8; font-size: 12px; text-transform: uppercase; }}
        .footer {{ margin-top: 24px; text-align: center; font-size: 12px; color: #64748b; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div>
                <h1 style="font-size: 24px; font-weight: 700;">🤖 ForexBot Live Monitor</h1>
                <p style="color: #94a3b8; font-size: 14px;">SLK & CRT Multi-Timeframe Strategy Engine</p>
            </div>
            <div class="header-actions">
                <a href="/live-log" class="btn btn-primary">📜 Live Logs</a>
                <span class="badge">● {BOT_STATUS['status']} ({BOT_STATUS['mode']})</span>
            </div>
        </div>

        <div class="grid">
            <div class="card">
                <h3>Account Balance</h3>
                <div class="value">${BOT_STATUS['account']['balance']:,.2f}</div>
            </div>
            <div class="card">
                <h3>Account Equity</h3>
                <div class="value">${BOT_STATUS['account']['equity']:,.2f}</div>
            </div>
            <div class="card">
                <h3>Daily Drawdown</h3>
                <div class="value" style="color: #10b981;">{BOT_STATUS['account']['daily_drawdown_pct']:.2f}%</div>
            </div>
            <div class="card">
                <h3>Active Symbols</h3>
                <div class="value" style="font-size: 18px;">EURUSD, GBPUSD, XAUUSD</div>
            </div>
        </div>

        <div class="table-card">
            <h2 style="font-size: 18px; margin-bottom: 12px;">📈 Open Positions ({len(BOT_STATUS['open_positions'])})</h2>
            <table>
                <thead>
                    <tr>
                        <th>Ticket</th>
                        <th>Symbol</th>
                        <th>Type</th>
                        <th>Volume</th>
                        <th>Open Price</th>
                        <th>Stop Loss</th>
                        <th>Take Profit</th>
                    </tr>
                </thead>
                <tbody>
                    {positions_rows}
                </tbody>
            </table>
        </div>

        <div class="table-card">
            <h2 style="font-size: 18px;">🎯 Latest Storyline & Signal</h2>
            <p style="color: #cbd5e1; font-size: 14px; margin-top: 8px;">{signal_info}</p>
        </div>

        <div class="footer">
            Bot Started: {BOT_STATUS['start_time']} | Last Refresh: {BOT_STATUS['last_update']} | Auto-refreshes every 10s • <a href="/live-log" style="color:#60a5fa; text-decoration:none;">View Live Logs</a> • <a href="/health" style="color:#60a5fa; text-decoration:none;">Health JSON</a>
        </div>
    </div>
</body>
</html>"""

    def _render_live_log_page(self) -> str:
        return """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ForexBot - Live Execution Logs Stream</title>
    <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { background: #090d16; color: #e2e8f0; font-family: 'Inter', sans-serif; padding: 16px; height: 100vh; display: flex; flex-direction: column; overflow: hidden; }
        .nav-bar { display: flex; justify-content: space-between; align-items: center; padding: 12px 16px; background: #131b2e; border: 1px solid #1e293b; border-radius: 10px; margin-bottom: 12px; }
        .nav-left { display: flex; align-items: center; gap: 12px; }
        .nav-title { font-size: 18px; font-weight: 700; color: #f8fafc; }
        .live-dot { width: 10px; height: 10px; background: #10b981; border-radius: 50%; display: inline-block; animation: pulse 1.5s infinite; }
        @keyframes pulse { 0% { opacity: 1; transform: scale(1); } 50% { opacity: 0.4; transform: scale(1.2); } 100% { opacity: 1; transform: scale(1); } }
        
        .controls { display: flex; align-items: center; gap: 10px; }
        .btn { padding: 6px 14px; border-radius: 6px; font-size: 13px; font-weight: 600; text-decoration: none; border: none; cursor: pointer; transition: all 0.2s; display: inline-flex; align-items: center; gap: 6px; }
        .btn-dash { background: #1e293b; color: #94a3b8; border: 1px solid #334155; }
        .btn-dash:hover { background: #334155; color: #f8fafc; }
        .btn-toggle { background: #059669; color: #ffffff; }
        .btn-toggle.paused { background: #d97706; }
        .btn-clear { background: #334155; color: #cbd5e1; }
        .btn-clear:hover { background: #475569; }

        .filter-input { background: #0f172a; border: 1px solid #334155; color: #f8fafc; padding: 6px 12px; border-radius: 6px; font-size: 13px; width: 180px; }
        .filter-input:focus { outline: none; border-color: #3b82f6; }

        .terminal-container { flex: 1; background: #070a12; border: 1px solid #1e293b; border-radius: 10px; padding: 14px; overflow-y: auto; font-family: 'JetBrains Mono', monospace; font-size: 13px; line-height: 1.6; white-space: pre-wrap; word-break: break-all; }
        
        .log-line { padding: 2px 0; border-bottom: 1px solid #111827; }
        .log-time { color: #64748b; }
        .log-info { color: #38bdf8; }
        .log-warn { color: #fbbf24; font-weight: 600; }
        .log-err { color: #f87171; font-weight: 700; }
        .log-crit { color: #f43f5e; font-weight: 700; background: #4c0519; padding: 2px 4px; border-radius: 4px; }
        .log-signal { color: #4ade80; font-weight: 700; }
        .log-order { color: #a78bfa; font-weight: 700; }

        .footer-bar { display: flex; justify-content: space-between; align-items: center; padding-top: 10px; font-size: 12px; color: #64748b; }
    </style>
</head>
<body>
    <div class="nav-bar">
        <div class="nav-left">
            <span class="live-dot"></span>
            <span class="nav-title">ForexBot Live Log Terminal</span>
            <span id="lineCount" style="font-size: 12px; color: #94a3b8; background: #0f172a; padding: 3px 8px; border-radius: 4px;">0 lines</span>
        </div>
        <div class="controls">
            <input type="text" id="searchInput" class="filter-input" placeholder="🔍 Filter logs..." oninput="applyFilter()">
            <button id="autoscrollBtn" class="btn btn-toggle" onclick="toggleAutoScroll()">Auto-Scroll: ON</button>
            <button class="btn btn-clear" onclick="clearConsole()">🧹 Clear View</button>
            <a href="/" class="btn btn-dash">📊 Dashboard</a>
        </div>
    </div>

    <div id="terminal" class="terminal-container">Connecting to live log feed...</div>

    <div class="footer-bar">
        <span id="updateStatus">Connecting to /api/logs...</span>
        <span>Polling rate: 1.5s • Direct API: <a href="/api/logs" target="_blank" style="color: #38bdf8; text-decoration: none;">/api/logs</a></span>
    </div>

    <script>
        let autoScroll = true;
        let allLogs = [];
        const terminal = document.getElementById("terminal");
        const autoscrollBtn = document.getElementById("autoscrollBtn");
        const searchInput = document.getElementById("searchInput");
        const lineCount = document.getElementById("lineCount");
        const updateStatus = document.getElementById("updateStatus");

        function toggleAutoScroll() {
            autoScroll = !autoScroll;
            if (autoScroll) {
                autoscrollBtn.innerText = "Auto-Scroll: ON";
                autoscrollBtn.className = "btn btn-toggle";
                scrollToBottom();
            } else {
                autoscrollBtn.innerText = "Auto-Scroll: OFF";
                autoscrollBtn.className = "btn btn-toggle paused";
            }
        }

        function scrollToBottom() {
            if (autoScroll) {
                terminal.scrollTop = terminal.scrollHeight;
            }
        }

        function clearConsole() {
            terminal.innerHTML = '<span style="color:#64748b;">[Console cleared locally. New incoming logs will appear below.]</span>';
        }

        function formatLine(line) {
            let cls = "";
            if (line.includes("SIGNAL DETECTED") || line.includes("Bullish") || line.includes("Bearish")) {
                cls = "log-signal";
            } else if (line.includes("ORDER FILLED") || line.includes("Sending Order") || line.includes("POSITION CLOSED")) {
                cls = "log-order";
            } else if (line.includes("CRITICAL") || line.includes("KILL_SWITCH")) {
                cls = "log-crit";
            } else if (line.includes("ERROR") || line.includes("failed")) {
                cls = "log-err";
            } else if (line.includes("WARNING") || line.includes("WARN")) {
                cls = "log-warn";
            } else if (line.includes("INFO")) {
                cls = "log-info";
            }

            // Escape HTML characters
            const safe = line.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
            return `<div class="log-line ${cls}">${safe}</div>`;
        }

        function applyFilter() {
            const query = searchInput.value.toLowerCase().trim();
            if (!query) {
                renderLogs(allLogs);
                return;
            }
            const filtered = allLogs.filter(l => l.toLowerCase().includes(query));
            renderLogs(filtered);
        }

        function renderLogs(logArray) {
            if (!logArray || logArray.length === 0) {
                terminal.innerHTML = '<div style="color:#64748b;">No matching logs found.</div>';
                return;
            }
            terminal.innerHTML = logArray.map(formatLine).join("");
            lineCount.innerText = logArray.length + " lines";
            scrollToBottom();
        }

        async function fetchLogs() {
            try {
                const res = await fetch("/api/logs?lines=300");
                if (!res.ok) throw new Error("HTTP " + res.status);
                const data = await res.json();
                allLogs = data.logs || [];
                applyFilter();
                updateStatus.innerText = "🟢 Connected | Last poll: " + new Date().toLocaleTimeString();
            } catch (err) {
                updateStatus.innerText = "🔴 Log stream disconnected: " + err.message;
            }
        }

        // Start real-time polling
        fetchLogs();
        setInterval(fetchLogs, 1500);

        // Detect user manual scroll up to temporarily pause autoscroll
        terminal.addEventListener("scroll", () => {
            const isNearBottom = terminal.scrollHeight - terminal.scrollTop - terminal.clientHeight < 40;
            if (!isNearBottom && autoScroll) {
                // User scrolled up
            }
        });
    </script>
</body>
</html>"""


def start_web_server(port: int = None, host: str = "0.0.0.0") -> HTTPServer:
    """Starts the dashboard and log streaming server in a non-blocking daemon thread."""
    if port is None:
        port = int(os.getenv("PORT", "8080"))

    server = HTTPServer((host, port), BotDashboardHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logger.info(f"Web Dashboard, Health API & Live Log Stream active on http://{host}:{port}/ (Logs: /live-log)")
    return server


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    srv = start_web_server()
    print("Dashboard and Live Log Stream running on port 8080. Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        srv.shutdown()
