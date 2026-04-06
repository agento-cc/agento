ARG SANDBOX_IMAGE=agento-sandbox:latest
FROM ${SANDBOX_IMAGE}

USER root

RUN apt-get update && \
    apt-get install -y --no-install-recommends cron python3 python3-venv procps logrotate && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Install uv
RUN curl -LsSf https://astral.sh/uv/install.sh | sh && \
    mv /root/.local/bin/uv /usr/local/bin/uv

# Install Python project
COPY pyproject.toml /opt/cron-agent/pyproject.toml
COPY README.md /opt/cron-agent/README.md
COPY src/agento/ /opt/cron-agent/src/agento/
RUN cd /opt/cron-agent && \
    uv venv .venv && \
    uv pip install --python .venv/bin/python -e . && \
    chmod -R a+rX /opt/cron-agent/.venv && \
    chown -R agent /opt/cron-agent

COPY docker/cron/run.sh /opt/cron-agent/run.sh
RUN chmod +x /opt/cron-agent/run.sh

COPY docker/cron/logrotate-agent.conf /opt/cron-agent/logrotate-agent.conf

COPY docker/cron/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
