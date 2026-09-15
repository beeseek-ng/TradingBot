# ==============================================================================
# ForexBot - Production Multi-Stage Dockerfile for Heroku & Cloud Deployments
# ==============================================================================

FROM ubuntu:22.04

# Prevent interactive prompts during apt install
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    WINEPREFIX=/opt/wine-mt5 \
    WINEDEBUG=-all \
    DISPLAY=:99 \
    PORT=8080

# 1. Install system utilities, Xvfb (Virtual Framebuffer), Wine, and Linux Python
RUN dpkg --add-architecture i386 && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        wget \
        unzip \
        xvfb \
        procps \
        git \
        wine64 \
        wine32 \
        wine \
        python3 \
        python3-pip \
        python3-setuptools \
        python3-wheel && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# 2. Setup Windows Python 3.9 and MetaTrader5 package inside Wine for Headless Live MT5
RUN mkdir -p /opt/wine-mt5/drive_c/Python39 && \
    curl -sSL -o /tmp/python-39.zip https://www.python.org/ftp/python/3.9.13/python-3.9.13-embed-amd64.zip && \
    unzip -q -o /tmp/python-39.zip -d /opt/wine-mt5/drive_c/Python39 && \
    rm /tmp/python-39.zip && \
    sed -i 's/#import site/import site/' /opt/wine-mt5/drive_c/Python39/python39._pth && \
    echo "Lib/site-packages" >> /opt/wine-mt5/drive_c/Python39/python39._pth && \
    curl -sSL -o /opt/wine-mt5/drive_c/Python39/get-pip.py https://bootstrap.pypa.io/pip/3.9/get-pip.py && \
    Xvfb :99 -screen 0 1024x768x16 & \
    sleep 2 && \
    wine /opt/wine-mt5/drive_c/Python39/python.exe /opt/wine-mt5/drive_c/Python39/get-pip.py --no-warn-script-location && \
    wine /opt/wine-mt5/drive_c/Python39/Scripts/pip.exe install --no-cache-dir MetaTrader5 "numpy<2" pandas tabulate && \
    pkill Xvfb || true

# 3. Create app workspace
WORKDIR /app

# 4. Install native Linux Python dependencies
COPY requirements.txt /app/
RUN pip3 install --no-cache-dir -r requirements.txt

# 5. Copy application source code and datasets
COPY config.py strategy.py backtester.py main.py web_server.py test_forex_bot.py entrypoint.sh /app/
COPY data/ /app/data/

# Ensure entrypoint is executable and logs directory exists
RUN chmod +x /app/entrypoint.sh && mkdir -p /app/logs

# Expose default HTTP Port for Heroku Web Dyno / Dashboard
EXPOSE 8080

# Default entrypoint orchestrator
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["run"]
