#!/usr/bin/env bash
# ==============================================================================
# ForexBot - Wine MetaTrader 5 Live Launcher
# ==============================================================================

set -e

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

echo ""
echo "=================================================="
echo "      STARTING FOREXBOT WITH LIVE MT5 EXECUTION   "
echo "=================================================="
WINEPREFIX="$WINE_PREFIX_DIR" WINEDEBUG=-all wine "C:\\Python39\\python.exe" main.py --mode live "$@"

