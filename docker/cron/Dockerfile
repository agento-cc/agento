ARG SANDBOX_IMAGE=agento-sandbox:latest
FROM ${SANDBOX_IMAGE}

USER root

RUN apt-get update && \
    apt-get install -y --no-install-recommends cron python3 python3-venv procps logrotate && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Install uv
RUN curl -LsSf https://astral.sh/uv/install.sh | sh && \
    mv /root/.local/bin/uv /usr/local/bin/uv

# Install Python project using lockfile for reproducible builds
# UV_PYTHON_INSTALL_DIR: uv downloads a standalone Python and symlinks into
# .venv/bin/python.  Default location is /root/.local/share/uv/python/ which
# is inaccessible to the non-root 'agent' user.  Place it under /opt instead.
ENV UV_PYTHON_INSTALL_DIR=/opt/uv-python
COPY pyproject.toml uv.lock README.md /opt/cron-agent/
COPY src/agento/ /opt/cron-agent/src/agento/
RUN cd /opt/cron-agent && \
    uv venv .venv && \
    uv sync --frozen --no-dev && \
    chown -R agent /opt/cron-agent

COPY docker/cron/run.sh /opt/cron-agent/run.sh
RUN chmod +x /opt/cron-agent/run.sh

COPY docker/cron/logrotate-agent.conf /opt/cron-agent/logrotate-agent.conf

COPY docker/cron/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
