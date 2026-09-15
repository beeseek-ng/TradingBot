# ForexBot Commands & Quick Execution Guide

This file contains all the essential terminal commands to run the backtester, launch the bot, monitor logs, and execute tests.

---

## 📊 1. Historical Backtesting Commands

The backtesting engine is pure Python, operates on your CSV data, and works **100% natively on Linux, Mac, and Windows**.

### A. Run Backtest Across All Pairs
```bash
.venv/bin/python backtester.py --symbol ALL --lotsize fixed --tp 150 --sl 50
```

### B. Run Backtest on Specific Symbols

#### 1. Gold (XAUUSD) — Fixed 0.02 Lots
```bash
.venv/bin/python backtester.py --symbol XAUUSD --lotsize fixed --tp 150 --sl 50
```

#### 2. British Pound (GBPUSD) — Fixed 0.05 Lots
```bash
# Standard 1:3 Risk-to-Reward (150 pips Take Profit)
.venv/bin/python backtester.py --symbol GBPUSD --lotsize fixed --tp 150 --sl 50

# Extended 1:5 Risk-to-Reward (250 pips Take Profit runner)
.venv/bin/python backtester.py --symbol GBPUSD --lotsize fixed --tp 250 --sl 50
```

#### 3. Euro (EURUSD) — Fixed 0.05 Lots
```bash
.venv/bin/python backtester.py --symbol EURUSD --lotsize fixed --tp 150 --sl 50
```

### C. Useful Backtest Options & Flags
| Flag | Description | Default | Example |
| :--- | :--- | :--- | :--- |
| `--symbol` | Symbol to test (`ALL`, `EURUSD`, `GBPUSD`, `XAUUSD`) | `ALL` | `--symbol GBPUSD` |
| `--balance` | Initial simulated balance ($) | `10000.0` | `--balance 50000` |
| `--tp` | Take Profit target in pips | `150.0` | `--tp 250` |
| `--sl` | Stop Loss in pips | `50.0` | `--sl 50` |
| `--lotsize` | `fixed` (0.05 FX / 0.02 Gold) or `dynamic` (1% risk) | `fixed` | `--lotsize dynamic` |
| `--csv` | Custom historical CSV path | Automatic | `--csv data/custom.csv` |

---

## 🔴 2. Live & Paper Trading Execution

The bot now supports **two execution modes**:

### Mode A: Run on Linux (Live Paper Trading / Real-Time Simulation)
You can start the bot immediately on your Linux system without needing Windows. It runs the real-time SLK & CRT engine, streams candles, manages virtual positions, enforces 50-pip SL and 150-pip TP, and logs all trade alerts:
```bash
python3 main.py
# or explicitly:
.venv/bin/python main.py --mode paper
```

### Mode B: Run with MetaTrader 5 on Wine (Linux Live Execution)
To connect directly to your running MT5 terminal on Linux via Wine and execute live orders on your demo account:
```bash
./run_live_wine.sh
```
> [!IMPORTANT]
> **Enable Algo Trading in MT5**: Ensure the **"Algo Trading"** button in your MetaTrader 5 top toolbar is clicked and shows **Green (Active)**. (Or go to `Tools` -> `Options` -> `Expert Advisors` -> check `Allow Algo Trading`).

---

### Mode C: Run on Windows / Windows VPS (Native Live Execution)
When running on a native Windows machine or Windows VPS with MT5 open:
```cmd
python main.py --mode live
```

## 📝 3. Real-Time Log Monitoring

To view live bot output and trade alerts streamed in real-time:
```bash
tail -f logs/bot_activity.log
```

To view the last 100 log lines:
```bash
tail -n 100 logs/bot_activity.log
```

---

## 🧪 4. Running Unit Tests

Run the full automated test suite (verifying pip math, risk management, CRT sweeps, and SLK structure):
```bash
.venv/bin/pytest -v
```

---

## 🐳 5. Docker & Heroku Deployment Commands

### A. Run with Docker Compose:
```bash
# Paper trading simulation with Web Dashboard on http://localhost:8080:
docker compose up --build forexbot-paper

# Live MT5 trading mode:
docker compose --profile live up --build forexbot-live
```

### B. Deploy to Heroku:
```bash
# 1. Create app and set container stack:
heroku create my-forex-bot
heroku stack:set container

# 2. Set credentials:
heroku config:set BOT_MODE=live MT5_LOGIN=5055872290 MT5_PASSWORD=RhPwCr*0 MT5_SERVER=MetaQuotes-Demo

# 3. Deploy and scale:
git push heroku main
heroku ps:scale web=1

# 4. View logs & open live dashboard:
heroku logs --tail
heroku open
```
*(For complete details, see [HEROKU_DEPLOYMENT_GUIDE.md](file:///home/solodev/Documents/Trading_Bot/HEROKU_DEPLOYMENT_GUIDE.md)).*

