#!/usr/bin/env bash
# ==============================================================================
# ForexBot Docker & Heroku Container Entrypoint
# ==============================================================================

set -e

# Load environment file if present (data.env or .env)
if [ -f "data.env" ]; then
    echo "[INFO] Loading environment variables from data.env..."
    set -a
    . ./data.env
    set +a
elif [ -f ".env" ]; then
    echo "[INFO] Loading environment variables from .env..."
    set -a
    . ./.env
    set +a
fi

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
    rm -f /tmp/.X99-lock /tmp/.X11-unix/X99 2>/dev/null || true
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
    configure_mt5_autotrading
}

# Automatically configure MT5 common.ini and terminal.ini with AutoTrading / Experts enabled
configure_mt5_autotrading() {
    echo "[INFO] Configuring MT5 AutoTrading and Expert Advisor permissions..."
    local config_dirs=(
        "$WINE_PREFIX_DIR/drive_c/Program Files/MetaTrader 5/config"
        "$WINE_PREFIX_DIR/drive_c/Program Files/MetaTrader 5/bases"
        "$WINE_PREFIX_DIR/drive_c/users/root/AppData/Roaming/MetaQuotes/Terminal/Common"
        "$WINE_PREFIX_DIR/drive_c/users/root/Application Data/MetaQuotes/Terminal/Common"
    )

    for cfg_dir in "${config_dirs[@]}"; do
        mkdir -p "$cfg_dir"
        cat << 'EOF' > "$cfg_dir/common.ini"
[Common]
ExpertsEnable=1
ExpertsDll=1
ExpertsExp=1
ExpertsTrades=1

[Experts]
AllowLiveTrading=1
AllowDllImport=1
Enabled=1
Account=1
Profile=1
Chart=1
Market=1
News=1
Signal=1
EOF
        cat << 'EOF' > "$cfg_dir/terminal.ini"
[Common]
ExpertsEnable=1
ExpertsDll=1
ExpertsExp=1
ExpertsTrades=1

[Experts]
AllowLiveTrading=1
AllowDllImport=1
Enabled=1
Account=1
Profile=1
Chart=1
Market=1
News=1
Signal=1
EOF
    done

    # Replicate to any existing terminal hash folders under AppData
    for sub in "$WINE_PREFIX_DIR/drive_c/users/"*"/AppData/Roaming/MetaQuotes/Terminal/"*; do
        if [ -d "$sub" ] && [ "$(basename "$sub")" != "Common" ]; then
            mkdir -p "$sub/config"
            cp -f "$WINE_PREFIX_DIR/drive_c/Program Files/MetaTrader 5/config/common.ini" "$sub/config/common.ini" 2>/dev/null || true
            cp -f "$WINE_PREFIX_DIR/drive_c/Program Files/MetaTrader 5/config/terminal.ini" "$sub/config/terminal.ini" 2>/dev/null || true
        fi
    done
}

# Background daemon to ensure AlgoTrading is activated on X11
activate_x11_autotrading() {
    (
        sleep 12
        for i in 1 2 3 4 5; do
            if command -v xdotool > /dev/null && [ -n "$DISPLAY" ]; then
                DISPLAY=:99 xdotool key ctrl+e 2>/dev/null || true
                DISPLAY=:99 xdotool search --name "MetaTrader" windowactivate --sync key ctrl+e 2>/dev/null || true
            fi
            sleep 6
        done
    ) &
}

# 1. Live Mode with MT5 on Wine
if [ "$BOT_MODE" = "live" ]; then
    echo "[INFO] Attempting to start ForexBot in LIVE MetaTrader 5 mode under Wine..."
    start_xvfb || true
    export WINEDEBUG=-all
    export WINEDLLOVERRIDES="mscoree,mshtml=;winedbg.exe=d"
    export WINEPREFIX="$WINE_PREFIX_DIR"
    export PYTHONPATH="Z:\\app:."
    export PYTHONIOENCODING="utf-8"
    ensure_mt5_terminal || true
    configure_mt5_autotrading || true
    activate_x11_autotrading || true
    
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
