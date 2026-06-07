FROM node:24-slim

# Python 3 for the MCP bridge script
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-pip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python MCP bridge dependencies first (layer-cached)
COPY requirements.txt .
RUN pip3 install --break-system-packages --no-cache-dir -r requirements.txt

# Install OpenClaw globally
RUN npm install -g openclaw@latest

# Copy MCP bridge and workspace files
COPY mcp_bridge.py .
COPY heartbeat.py .
COPY workspace/ /app/workspace/

# Entrypoint generates openclaw.json from env vars and starts the gateway
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
