#!/usr/bin/env bash
# ==============================================================================
# ForexBot - Wine MetaTrader 5 Live Launcher
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

WINE_PREFIX_DIR="${WINEPREFIX:-$HOME/.mt5}"
PYTHON_DIR="$WINE_PREFIX_DIR/drive_c/Python39"

echo "=================================================="
echo "      FOREXBOT WINE MT5 LAUNCHER                  "
echo "=================================================="
echo "Target Wine Prefix: $WINE_PREFIX_DIR"
echo "Target Python Dir:  $PYTHON_DIR"
echo ""

# 1. Check if Wine is installed
if ! command -v wine &> /dev/null; then
    echo "[ERROR] Wine is not installed on this system. Please install Wine first."
    exit 1
fi

# 2. Check/Setup Windows Python inside Wine Prefix
if [ ! -f "$PYTHON_DIR/python.exe" ]; then
    echo "[INFO] Setting up Windows Python 3.9 inside Wine..."
    mkdir -p "$PYTHON_DIR"
    curl -sSL -o /tmp/python-39.zip https://www.python.org/ftp/python/3.9.13/python-3.9.13-embed-amd64.zip
    unzip -q -o /tmp/python-39.zip -d "$PYTHON_DIR"
fi

# 3. Configure .pth file to allow pip and standard libraries
if [ -f "$PYTHON_DIR/python39._pth" ]; then
    sed -i 's/#import site/import site/' "$PYTHON_DIR/python39._pth"
    if ! grep -q "Lib/site-packages" "$PYTHON_DIR/python39._pth"; then
        echo "Lib/site-packages" >> "$PYTHON_DIR/python39._pth"
    fi
fi

# 4. Install pip if not present
if [ ! -f "$PYTHON_DIR/Scripts/pip.exe" ]; then
    echo "[INFO] Installing pip for Windows Python..."
    curl -sSL -o "$PYTHON_DIR/get-pip.py" https://bootstrap.pypa.io/pip/3.9/get-pip.py
    WINEPREFIX="$WINE_PREFIX_DIR" WINEDEBUG=-all wine "C:\\Python39\\python.exe" "C:\\Python39\\get-pip.py" --no-warn-script-location
fi

# 5. Install required packages (MetaTrader5, pandas, numpy, tabulate)
echo "[INFO] Ensuring MetaTrader5 and dependencies are installed..."
WINEPREFIX="$WINE_PREFIX_DIR" WINEDEBUG=-all wine "C:\\Python39\\Scripts\\pip.exe" install --quiet MetaTrader5 "numpy<2" pandas tabulate

# 6. Configure MT5 AutoTrading and Expert Advisor settings
configure_mt5_autotrading() {
    echo "[INFO] Configuring MT5 AutoTrading and Expert Advisor permissions..."
    local config_dirs=(
        "$WINE_PREFIX_DIR/drive_c/Program Files/MetaTrader 5/config"
        "$WINE_PREFIX_DIR/drive_c/Program Files/MetaTrader 5/bases"
        "$WINE_PREFIX_DIR/drive_c/users/$(whoami)/AppData/Roaming/MetaQuotes/Terminal/Common"
        "$WINE_PREFIX_DIR/drive_c/users/$(whoami)/Application Data/MetaQuotes/Terminal/Common"
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
}

configure_mt5_autotrading || true

echo ""
echo "=================================================="
echo "      STARTING FOREXBOT WITH LIVE MT5 EXECUTION   "
echo "=================================================="
WINEPREFIX="$WINE_PREFIX_DIR" WINEDEBUG=-all wine "C:\\Python39\\python.exe" main.py --mode live "$@"

