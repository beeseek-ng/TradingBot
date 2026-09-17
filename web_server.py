"""
ForexBot Web Server & Health Dashboard
=======================================
Lightweight HTTP server designed for Heroku Web Dynos and cloud monitoring.
Provides real-time system status, uptime, account health, and open positions.
"""

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict

logger = logging.getLogger("ForexBot.Web")

# Global state shared across the bot and web monitor
BOT_STATUS: Dict[str, Any] = {
    "status": "INITIALIZING",
    "mode": os.getenv("BOT_MODE", "live").upper(),
    "start_time": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
    "account": {
        "login": os.getenv("MT5_LOGIN", "5055872290"),
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


class BotDashboardHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the status dashboard."""

    def log_message(self, format, *args):
        # Suppress verbose standard HTTP access logging to keep console clean
        pass

    def do_GET(self):
        if self.path in ["/health", "/healthz", "/status"]:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(BOT_STATUS, indent=2).encode("utf-8"))
            return

        # Main HTML Dashboard
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()

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

        html = f"""<!DOCTYPE html>
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
            <div>
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
            Bot Started: {BOT_STATUS['start_time']} | Last Refresh: {BOT_STATUS['last_update']} | Auto-refreshes every 10s
        </div>
    </div>
</body>
</html>"""
        self.wfile.write(html.encode("utf-8"))


def start_web_server(port: int = None, host: str = "0.0.0.0") -> HTTPServer:
    """Starts the dashboard server in a daemon thread."""
    if port is None:
        port = int(os.getenv("PORT", "8080"))

    server = HTTPServer((host, port), BotDashboardHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logger.info(f"Web Dashboard & Health Endpoint active on http://{host}:{port}/")
    return server


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    srv = start_web_server()
    print("Dashboard running. Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        srv.shutdown()
