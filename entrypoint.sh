#!/usr/bin/env bash
# ==============================================================================
# ForexBot Docker & Heroku Container Entrypoint
# ==============================================================================

set -e

BOT_MODE="${BOT_MODE:-live}"
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

# 1. Live Mode with MT5 on Wine (Default)
if [ "$BOT_MODE" = "live" ]; then
    echo "[INFO] Starting ForexBot in LIVE MetaTrader 5 mode under Wine..."
    start_xvfb
    export WINEDEBUG=-all
    export WINEPREFIX="$WINE_PREFIX_DIR"
    ensure_mt5_terminal
    
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
        ensure_mt5_terminal
        exec wine "$PYTHON_WINE_EXE" main.py --mode live
    else
        exec python3 main.py --mode paper
    fi
fi
