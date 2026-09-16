# ForexBot - MetaTrader 5 Algorithmic FX & Gold Trading Bot 🚀

A production-ready, object-oriented algorithmic trading bot engineered for **MetaTrader 5 (MT5)**, **Wine (Linux)**, and **Windows**. 

It implements the **SLK (Structure, Liquidity, Key Level)**, **CRT (Candle Range Theory)**, and **ABC/XYZ Multi-Timeframe** price-action strategy across **EURUSD**, **GBPUSD**, and **XAUUSD (Gold)**.

---

## 📑 Table of Contents
1. [Strategy Overview (SLK & CRT)](#-strategy-overview)
2. [Project Architecture](#-project-architecture)
3. [First-Time Installation & Setup](#-first-time-installation--setup)
4. [How to Operate the Bot (3 Modes)](#-how-to-operate-the-bot)
   - [Mode 1: Historical Backtesting](#mode-1-historical-backtesting-csv-data)
   - [Mode 2: Real-Time Paper Trading](#mode-2-real-time-paper-trading-simulation)
   - [Mode 3: Live MT5 Execution](#mode-3-live-metatrader-5-execution-demo--real)
5. [Risk Management & Guardrails](#-risk-management--guardrails)
6. [Automated Unit Testing](#-automated-unit-testing)
7. [Configuration Guide](#-configuration-guide)

---

## 🧠 Strategy Overview

The bot operates without lagging indicators, executing purely on price action, institutional liquidity, and structural shifts:

### 1. Structure, Liquidity & Key Levels (SLK)
- **Market Storyline & Environment**: Classifies market context into `UPTREND`, `DOWNTREND`, `RANGING`, or `CHOPPY`.
- **Market Phases**: Distinguishes between `EXPANSION` (displacement) and `REVERSAL` (liquidity purges + Change of Character).
- **Key Levels & Imbalances**: Automatically locates multi-tested A-shape resistance peaks, V-shape support valleys, and 3-candle Fair Value Gaps (FVG).
- **Disrespected Key Levels (Breakers)**: Enters when a key level is impulsively broken (creating an FVG), retraced into, and confirmed by a local liquidity sweep.

### 2. Candle Range Theory (CRT)
- Identifies liquidity sweeps where price expands past prior candle highs/lows and closes back inside the prior range, targeting opposing high-timeframe liquidity pools.

### 3. Execution Rules
- **Execution Timeframes**: 2H, 1H, and 15M (M15 trigger).
- **Session Timings**: Active only during **London (`07:00 - 12:00 UTC`)** and **New York (`12:00 - 20:00 UTC`)**.
- **Risk / Reward & Lot Sizing**:
  - **EURUSD & GBPUSD**: `0.10` lots | **10.0 pips SL** ($10.00 risk) | **30.0 pips TP** ($30.00 reward, 1:3 RR) | **50.0 pips TP2** ($50.00 reward, 1:5 RR).
  - **XAUUSD (Gold)**: `0.02` lots | **50.0 pips SL** ($10.00 risk) | **150.0 pips TP** ($30.00 reward, 1:3 RR) | **250.0 pips TP2** ($50.00 reward, 1:5 RR).

---

## 📁 Project Architecture

```
Trading_Bot/
├── data/                      # Historical M15 CSV data (EURUSD, GBPUSD, XAUUSD)
├── logs/                      # Real-time execution logs (bot_activity.log)
├── config.py                  # Account credentials, lot sizes, risk & SL/TP settings
├── strategy.py                # SLK, CRT, Market Classifier, and signal generation
├── backtester.py              # Multi-timeframe zero-lookahead backtest engine
├── main.py                    # Live orchestration engine (supports MT5 & Paper trading)
├── web_server.py              # Live HTML status dashboard & Heroku $PORT health endpoint
├── run_live_wine.sh           # One-click launcher for MT5 running under Wine on Linux
├── test_forex_bot.py          # Automated pytest suite (pip math, risk, CRT, SLK)
├── Dockerfile                 # Production headless multi-stage container
├── docker-compose.yml         # Local Docker testing for live & paper trading
├── heroku.yml                 # Heroku container deployment manifest
├── entrypoint.sh              # Container bootstrap and process manager
├── HEROKU_DEPLOYMENT_GUIDE.md # Complete step-by-step Heroku deployment tutorial
├── COMMANDS.md                # Quick CLI cheatsheet
├── requirements.txt           # Python dependencies
└── README.md                  # Documentation & User Guide
```

---

## 🛠️ First-Time Installation & Setup

### 1. Clone the Repository
```bash
git clone git@github.com:emdevelopa/TradingBot.git
cd TradingBot
```

### 2. Create and Activate a Virtual Environment
```bash
python3 -m venv .venv
source .venv/bin/activate    # Linux / macOS
# On Windows: .venv\Scripts\activate
```

### 3. Install Requirements
```bash
pip install -r requirements.txt
```

---

## 🎮 How to Operate the Bot

### Mode 1: Historical Backtesting (CSV Data)
The backtester evaluates the strategy across years of historical data in seconds with detailed performance metrics.

```bash
# Backtest all pairs (EURUSD, GBPUSD, XAUUSD):
python backtester.py --symbol ALL --lotsize fixed --tp 150 --sl 50

# Backtest Gold (XAUUSD) with 150-pip TP:
python backtester.py --symbol XAUUSD --lotsize fixed --tp 150 --sl 50

# Backtest GBPUSD with 250-pip TP runner:
python backtester.py --symbol GBPUSD --lotsize fixed --tp 250 --sl 50
```

---

### Mode 2: Real-Time Paper Trading (Simulation)
Run real-time paper trading on your machine without connecting to MetaTrader. It replays candle feeds, runs the full SLK/CRT signal engine, and tracks virtual positions:

```bash
python main.py --mode paper
```

---

### Mode 3: Live MetaTrader 5 Execution (Demo / Real)

#### A. Running on Linux via Wine (e.g. Ubuntu, Zorin OS, Mint, Debian):
Make sure your MetaTrader 5 is running in Wine, then simply launch:
```bash
./run_live_wine.sh
```

#### B. Running on Windows / Windows VPS:
Open MetaTrader 5, log into your account, and run:
```cmd
python main.py --mode live
```

> [!IMPORTANT]
> **Enable Algo Trading in MT5**: Ensure the **"Algo Trading"** button in the MetaTrader 5 top toolbar is turned **ON (Green)**. (Or navigate to `Tools` ➔ `Options` ➔ `Expert Advisors` ➔ check `Allow Algo Trading`).

---

## 🐳 Docker & Heroku Cloud Deployment

### 1. Quick Deploy to Heroku
ForexBot is fully Dockerized and ready for 1-click cloud deployment to Heroku using `heroku.yml`:

```bash
# 1. Create a new Heroku container app:
heroku create my-forex-bot
heroku stack:set container

# 2. Set your MT5 credentials & parameters:
heroku config:set BOT_MODE=live MT5_LOGIN=5055872290 MT5_PASSWORD=RhPwCr*0 MT5_SERVER=MetaQuotes-Demo

# 3. Deploy to Heroku:
git push heroku main
heroku ps:scale web=1

# 4. Open Live Web Dashboard:
heroku open
```
*(For complete step-by-step instructions, see the [HEROKU_DEPLOYMENT_GUIDE.md](file:///home/solodev/Documents/Trading_Bot/HEROKU_DEPLOYMENT_GUIDE.md)).*

---

### 2. Run with Docker Locally
```bash
# Start real-time paper trading container with Web Dashboard:
docker compose up --build forexbot-paper

# Access Web Dashboard at:
# http://localhost:8080/
```

---

## 📝 Monitoring Live Logs & Dashboard

- **Terminal Logs**:
  ```bash
  tail -f logs/bot_activity.log
  # Or on Heroku:
  heroku logs --tail
  ```
- **Web Dashboard**: Access `http://localhost:8080/` (or `https://your-app.herokuapp.com/`) to view live balance, equity, daily drawdown, open positions, and latest signals.


---

## 🛡️ Risk Management & Guardrails

1. **Prop Firm 4.5% Daily Drawdown Kill-Switch**:
   - The bot records the starting daily account balance at `00:00 UTC`.
   - If current equity drops **4.5%** below the baseline, the kill-switch triggers: all positions are immediately liquidated, and trading halts for the day to preserve the account.
2. **Auto-Adaptive Order Filling**:
   - Automatically negotiates broker filling modes (`FOK`, `IOC`, `RETURN`) per symbol to prevent order rejections.
3. **Magic Number Isolation**:
   - Orders are tagged with `MAGIC_NUMBER = 101202` to safely manage bot trades independently of manual orders.

---

## 🧪 Automated Unit Testing

Run the test suite to verify math, risk rules, and strategy modules:
```bash
pytest -v
```

---

## ⚙️ Configuration Guide (`config.py`)

You can customize trading settings anytime in [`config.py`](file:///home/solodev/Documents/Trading_Bot/config.py):
- `ACCOUNT_LOGIN`, `ACCOUNT_PASSWORD`, `ACCOUNT_SERVER`: MT5 connection credentials.
- `FIXED_LOT_SIZES`: Set custom lots per pair (e.g., `{"EURUSD": 0.05, "GBPUSD": 0.05, "XAUUSD": 0.02}`).
- `DEFAULT_TP_PIPS`: `150.0` or `250.0`.
- `DEFAULT_SL_PIPS`: `50.0`.
- `GLOBAL_DAILY_DRAWDOWN_LIMIT`: Max daily drawdown limit (`0.045` = 4.5%).

---

## 📄 License
MIT License. Built for algorithmic trading research and execution.
