#!/usr/bin/env bash
# ==============================================================================
# ForexBot Docker & Heroku Container Entrypoint
# ==============================================================================

set -e

BOT_MODE="${BOT_MODE:-auto}"
WINE_PREFIX_DIR="${WINEPREFIX:-/opt/wine-mt5}"
PYTHON_WINE_EXE="$WINE_PREFIX_DIR/drive_c/Python39/python.exe"

echo "=================================================="
echo "      FOREXBOT CONTAINER INITIALIZATION           "
echo "=================================================="
echo "Container Mode:      $BOT_MODE"
echo "Web Port (\$PORT):    ${PORT:-8080}"
echo "Display Server:      :99 (Headless Xvfb)"
echo "Wine Prefix:         $WINE_PREFIX_DIR"
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

# 1. Live Mode with MT5 on Wine
if [ "$BOT_MODE" = "live" ]; then
    echo "[INFO] Starting ForexBot in LIVE MetaTrader 5 mode under Wine..."
    start_xvfb
    export WINEDEBUG=-all
    export WINEPREFIX="$WINE_PREFIX_DIR"
    
    if [ -f "$PYTHON_WINE_EXE" ]; then
        exec wine "$PYTHON_WINE_EXE" main.py --mode live
    else
        echo "[WARN] Wine Python not found at $PYTHON_WINE_EXE, falling back to Linux Python..."
        exec python3 main.py --mode live
    fi

# 2. Paper Trading Simulation Mode (Native Linux Python)
elif [ "$BOT_MODE" = "paper" ]; then
    echo "[INFO] Starting ForexBot in PAPER TRADING simulation mode..."
    exec python3 main.py --mode paper

# 3. Auto Mode (Detects environment)
else
    echo "[INFO] Starting ForexBot in AUTO mode..."
    if [ -f "$PYTHON_WINE_EXE" ] && [ -n "$MT5_LOGIN" ]; then
        start_xvfb
        export WINEDEBUG=-all
        export WINEPREFIX="$WINE_PREFIX_DIR"
        exec wine "$PYTHON_WINE_EXE" main.py --mode live
    else
        exec python3 main.py --mode paper
    fi
fi
