FROM node:22-slim

LABEL description="MCP toolbox - secure credential broker for AI sandbox"

WORKDIR /app

COPY src/agento/toolbox/package.json src/agento/toolbox/package-lock.json ./
RUN npm ci --omit=dev

# Install Chromium + system dependencies for Playwright MCP browser tools
# Note: Google Chrome has no official Linux ARM64 build; Chromium supports ARM64
RUN npx playwright install --with-deps chromium

# Install poppler-utils for PDF-to-text conversion (pdftotext CLI)
RUN apt-get update && \
    apt-get install -y --no-install-recommends poppler-utils && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

COPY src/agento/toolbox/ .
COPY src/agento/modules/ /app/modules/core/

# OpenSearch uses self-signed certs on internal network
ENV NODE_TLS_REJECT_UNAUTHORIZED=0

EXPOSE 3001

CMD ["node", "server.js"]
