# 🚀 Complete Heroku & Docker Deployment Guide for ForexBot

This guide walks you step-by-step through deploying **ForexBot** to **Heroku** using Docker containers.

---

## 📋 Table of Contents
1. [Prerequisites](#-1-prerequisites)
2. [Method A: Deploy via Git & `heroku.yml` (Recommended)](#-2-method-a-deploy-via-git--herokuyml-recommended)
3. [Method B: Deploy via Heroku Container Registry (`docker push`)](#-3-method-b-deploy-via-heroku-container-registry-docker-push)
4. [Setting Up Heroku Config Vars (Environment Variables)](#-4-setting-up-heroku-config-vars)
5. [Monitoring Logs & Web Dashboard](#-5-monitoring-logs--web-dashboard)
6. [Local Testing with Docker & Docker Compose](#-6-local-testing-with-docker)
7. [Helpful Heroku CLI Commands](#-7-helpful-heroku-cli-commands)

---

## 🛠️ 1. Prerequisites

1. A **Heroku Account** ([Sign up at heroku.com](https://signup.heroku.com/)).
2. **Heroku CLI** installed on your machine:
   ```bash
   # On Ubuntu / Linux:
   sudo snap install --classic heroku
   # Or via npm:
   npm install -g heroku
   ```
3. Verify your Heroku login:
   ```bash
   heroku login
   ```

---

## ⚡ 2. Method A: Deploy via Git & `heroku.yml` (Recommended)

This is the easiest and most reliable method because Heroku builds the Docker container automatically directly from your repository.

### Step 1: Create a New Heroku Application
```bash
heroku create my-forex-trading-bot
```
*(Replace `my-forex-trading-bot` with your desired unique app name).*

### Step 2: Set the App Stack to `container`
```bash
heroku stack:set container --app my-forex-trading-bot
```

### Step 3: Configure Your Trading Parameters & Credentials
Set your MT5 credentials and trading mode in Heroku:

```bash
# Set Bot Mode: 'live' (for live MT5 execution) or 'paper' (for cloud paper simulation)
heroku config:set BOT_MODE=live --app my-forex-trading-bot

# Set MetaTrader 5 Demo/Live Credentials
heroku config:set MT5_LOGIN=5055872290 --app my-forex-trading-bot
heroku config:set MT5_PASSWORD="YourPasswordHere" --app my-forex-trading-bot
heroku config:set MT5_SERVER=MetaQuotes-Demo --app my-forex-trading-bot

# Enable Web Dashboard on Heroku $PORT
heroku config:set ENABLE_WEB_DASHBOARD=true --app my-forex-trading-bot
```

### Step 4: Add Heroku Git Remote and Deploy
```bash
# Link the Heroku remote to your repository
heroku git:remote -a my-forex-trading-bot

# Push and trigger the container build
git push heroku main
```

### Step 5: Start the Dyno
```bash
# Start the web dyno (includes web dashboard + bot engine)
heroku ps:scale web=1 --app my-forex-trading-bot
```

---

## 🐳 3. Method B: Deploy via Heroku Container Registry (`docker push`)

If you prefer to build the container image locally and push the pre-built image to Heroku:

```bash
# 1. Log in to Heroku Container Registry
heroku container:login

# 2. Build and push the container image
heroku container:push web --app my-forex-trading-bot

# 3. Release the image to start running
heroku container:release web --app my-forex-trading-bot
```

---

## ⚙️ 4. Setting Up Heroku Config Vars

You can view and modify your bot configuration anytime via the CLI or the Heroku Web Dashboard:

### Via CLI:
```bash
# View all active config variables:
heroku config --app my-forex-trading-bot

# Update a setting:
heroku config:set DEFAULT_TP_PIPS=150.0 --app my-forex-trading-bot
heroku config:set DEFAULT_SL_PIPS=50.0 --app my-forex-trading-bot
heroku config:set BOT_MODE=paper --app my-forex-trading-bot
```

### Supported Environment Variables:
| Variable | Description | Default |
| :--- | :--- | :--- |
| `BOT_MODE` | Execution mode: `live`, `paper`, or `auto` | `auto` |
| `MT5_LOGIN` | MetaTrader 5 account login number | `5055872290` |
| `MT5_PASSWORD` | MetaTrader 5 account password | `RhPwCr*0` |
| `MT5_SERVER` | Broker server name | `MetaQuotes-Demo` |
| `PORT` | Web dashboard port (Automatically provided by Heroku) | `8080` |
| `ENABLE_WEB_DASHBOARD` | Enable the HTML status monitor | `true` |
| `RISK_PER_TRADE` | Fractional equity risk for dynamic lot sizing | `0.01` (1%) |
| `GLOBAL_DAILY_DRAWDOWN_LIMIT` | Prop firm daily drawdown kill-switch | `0.045` (4.5%) |

---

## 📊 5. Monitoring Logs & Web Dashboard

### 1. View Live Terminal Logs in Real-Time:
```bash
heroku logs --tail --app my-forex-trading-bot
```

### 2. Open the Live Web Dashboard in Your Browser:
```bash
heroku open --app my-forex-trading-bot
```
Or navigate directly to `https://my-forex-trading-bot.herokuapp.com/` in your browser.

> [!TIP]
> **Health Check Endpoint**: You can ping `https://my-forex-trading-bot.herokuapp.com/health` using services like [UptimeRobot](https://uptimerobot.com) to keep the dyno awake and monitor bot health 24/7.

---

## 💻 6. Local Testing with Docker

Before deploying to the cloud, you can test the container locally on your machine:

### A. Run Real-Time Paper Trading with Docker Compose:
```bash
docker compose up --build forexbot-paper
```
Open [http://localhost:8080](http://localhost:8080) in your browser to view the live dashboard!

### B. Run Native Docker Commands:
```bash
# Build the image:
docker build -t forexbot:latest .

# Run Paper Trading mode:
docker run -p 8080:8080 -e BOT_MODE=paper forexbot:latest

# Run Historical Backtester inside Docker:
docker run --rm forexbot:latest python3 backtester.py --symbol ALL
```

---

## 🛠️ 7. Helpful Heroku CLI Commands

```bash
# Restart the bot dyno:
heroku restart --app my-forex-trading-bot

# Stop the bot:
heroku ps:scale web=0 --app my-forex-trading-bot

# Start the bot:
heroku ps:scale web=1 --app my-forex-trading-bot

# Open an interactive bash terminal inside your Heroku container:
heroku run bash --app my-forex-trading-bot
```
