#!/usr/bin/env bash
# ==============================================================================
# ForexBot Docker & Heroku Container Entrypoint
# ==============================================================================

set -e

# Support both BOT_MODE and EXECUTION_MODE env vars
BOT_MODE="${BOT_MODE:-${EXECUTION_MODE:-live}}"
BOT_MODE="$(echo "$BOT_MODE" | tr '[:upper:]' '[:lower:]')"

# Discover Wine Prefix and Python executable
WINE_PREFIX_DIR="${WINEPREFIX:-/opt/wine-mt5}"

# Check known candidate locations for Wine Python
if [ ! -f "$WINE_PREFIX_DIR/drive_c/Python39/python.exe" ]; then
    for candidate_dir in "/opt/wine-mt5" "$HOME/.mt5" "$HOME/.wine"; do
        if [ -f "$candidate_dir/drive_c/Python39/python.exe" ]; then
            WINE_PREFIX_DIR="$candidate_dir"
            break
        fi
    done
fi

PYTHON_WINE_EXE="$WINE_PREFIX_DIR/drive_c/Python39/python.exe"

echo "=================================================="
echo "      FOREXBOT CONTAINER INITIALIZATION           "
echo "=================================================="
echo "Container Mode:      $BOT_MODE"
echo "Web Port (\$PORT):    ${PORT:-8080}"
echo "Display Server:      :99 (Headless Xvfb)"
echo "Wine Prefix:         $WINE_PREFIX_DIR"
echo "Wine Python:         $PYTHON_WINE_EXE"
echo "=================================================="

# If custom command passed directly (e.g. bash, pytest, backtester.py), execute it
if [ "$#" -gt 0 ] && [ "$1" != "run" ]; then
    echo "[INFO] Executing custom container command: $@"
    exec "$@"
fi

# Function to start virtual framebuffer for headless Wine GUI operations
start_xvfb() {
    if ! pgrep -x "Xvfb" > /dev/null; then
        echo "[INFO] Starting virtual framebuffer Xvfb on display :99..."
        Xvfb :99 -screen 0 1024x768x16 -nolisten tcp &
        export DISPLAY=:99
        sleep 1
    fi
}

# Ensure MT5 Terminal exists inside Wine prefix
ensure_mt5_terminal() {
    local mt5_dir="$WINE_PREFIX_DIR/drive_c/Program Files/MetaTrader 5"
    if [ ! -f "$mt5_dir/terminal64.exe" ]; then
        echo "[INFO] MetaTrader 5 terminal not found. Initializing setup via silent installer..."
        start_xvfb
        mkdir -p "$mt5_dir"
        curl -sSL -o /tmp/mt5setup.exe https://download.mql5.com/cdn/web/metaquotes.software.corp/mt5/mt5setup.exe
        WINEDEBUG=-all WINEPREFIX="$WINE_PREFIX_DIR" DISPLAY=:99 wine /tmp/mt5setup.exe /auto || true
        rm -f /tmp/mt5setup.exe
    fi
}

# 1. Live Mode with MT5 on Wine
if [ "$BOT_MODE" = "live" ]; then
    echo "[INFO] Attempting to start ForexBot in LIVE MetaTrader 5 mode under Wine..."
    start_xvfb || true
    export WINEDEBUG=-all
    export WINEPREFIX="$WINE_PREFIX_DIR"
    export PYTHONPATH="."
    ensure_mt5_terminal || true
    
    if [ -f "$PYTHON_WINE_EXE" ]; then
        echo "[INFO] Launching Wine Python MT5 Bridge ($PYTHON_WINE_EXE)..."
        wine "$PYTHON_WINE_EXE" main.py --mode live || {
            echo "[WARN] Wine MT5 process failed. Falling back to Native Linux Python (Paper Mode)..."
            exec python3 main.py --mode paper
        }
    else
        echo "[WARN] Wine Python not found at $PYTHON_WINE_EXE. Running with Native Linux Python..."
        exec python3 main.py --mode live || exec python3 main.py --mode paper
    fi

# 2. Paper Trading Simulation Mode (Native Linux Python)
elif [ "$BOT_MODE" = "paper" ]; then
    echo "[INFO] Starting ForexBot in PAPER TRADING simulation mode..."
    exec python3 main.py --mode paper

# 3. Auto Mode (Detects environment)
else
    echo "[INFO] Starting ForexBot in AUTO mode..."
    if [ -f "$PYTHON_WINE_EXE" ]; then
        start_xvfb || true
        export WINEDEBUG=-all
        export WINEPREFIX="$WINE_PREFIX_DIR"
        export PYTHONPATH="."
        ensure_mt5_terminal || true
        wine "$PYTHON_WINE_EXE" main.py --mode live || {
            echo "[WARN] Wine MT5 failed, falling back to Paper Mode..."
            exec python3 main.py --mode paper
        }
    else
        exec python3 main.py --mode auto
    fi
fi
