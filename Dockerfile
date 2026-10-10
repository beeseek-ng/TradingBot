# ==============================================================================
# ForexBot - Production Dockerfile for Coolify & Cloud Deployments
# ==============================================================================

ARG BASE_IMAGE=tradingbot-base:latest
FROM ${BASE_IMAGE}

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    WINEPREFIX=/opt/wine-mt5 \
    WINEDEBUG=-all \
    DISPLAY=:99 \
    PORT=8080 \
    BOT_MODE=live

WORKDIR /app

# Install native Linux Python dependencies if requirements changed
COPY requirements.txt /app/
RUN pip3 install --no-cache-dir -r requirements.txt || true

# Copy application source code and datasets
COPY config.py strategy.py backtester.py main.py web_server.py test_forex_bot.py entrypoint.sh /app/
COPY data/ /app/data/

# Ensure entrypoint is executable and logs directory exists
RUN chmod +x /app/entrypoint.sh && mkdir -p /app/logs

# Expose default HTTP Port for Web Dashboard & API
EXPOSE 8080

# Default entrypoint orchestrator
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["run"]
