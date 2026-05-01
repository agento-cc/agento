FROM node:22-slim

LABEL description="MCP toolbox - thin runtime, source mounted at runtime"

WORKDIR /app

# Subdirectory of the build context that contains package.json + package-lock.json.
# Default '.' = client-side context (`.agento/docker/toolbox/` materialized via
# `agento install`). Dev compose overrides to 'src/agento/toolbox'.
ARG PACKAGE_DIR=.

COPY ${PACKAGE_DIR}/package.json ${PACKAGE_DIR}/package-lock.json ./
RUN npm ci --omit=dev

# Install Chromium + system dependencies for Playwright MCP browser tools.
# Note: Google Chrome has no official Linux ARM64 build; Chromium supports ARM64.
RUN npx playwright install --with-deps chromium

# poppler-utils for PDF-to-text conversion (pdftotext CLI).
RUN apt-get update && \
    apt-get install -y --no-install-recommends poppler-utils && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# OpenSearch uses self-signed certs on internal network
ENV NODE_TLS_REJECT_UNAUTHORIZED=0
ENV NODE_PATH=/app/node_modules

EXPOSE 3001

# Source code (server.js, adapters/, etc.) is bind-mounted to /opt/agento-toolbox-src/.
# Modules from agento.modules + app/code are mounted to /app/modules/{core,user}.
CMD ["node", "/opt/agento-toolbox-src/server.js"]
