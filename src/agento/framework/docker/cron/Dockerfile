ARG SANDBOX_IMAGE=agento-sandbox:latest
FROM ${SANDBOX_IMAGE}

USER root

RUN apt-get update && \
    apt-get install -y --no-install-recommends cron python3 python3-venv procps logrotate && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

RUN curl -LsSf https://astral.sh/uv/install.sh | sh && \
    mv /root/.local/bin/uv /usr/local/bin/uv

ENV UV_PYTHON_INSTALL_DIR=/opt/uv-python

# Subdirectory of the build context that contains pyproject.toml + uv.lock.
# Default '.' = client-side context (`.agento/docker/cron/` materialized via
# `agento install`). Dev compose builds with context=repo-root and keeps '.'
# (root repo has pyproject.toml + uv.lock at top level).
ARG PYPROJECT_DIR=.
# Subdirectory of the build context that contains the cron service scripts.
# Default '.' = client-side context. Dev compose overrides to
# 'src/agento/framework/docker/cron'.
ARG SCRIPTS_DIR=.

# Container venv with native deps (cryptography, pymysql, etc.) only.
# --no-install-project: agento itself is bind-mounted from host site-packages
# at runtime via PYTHONPATH; we only need its dependencies pre-installed here.
COPY ${PYPROJECT_DIR}/pyproject.toml ${PYPROJECT_DIR}/uv.lock /opt/cron-agent/
RUN cd /opt/cron-agent && \
    uv venv .venv && \
    uv sync --frozen --no-install-project --no-dev && \
    chown -R agent /opt/cron-agent

ENV PATH=/opt/cron-agent/.venv/bin:$PATH

COPY ${SCRIPTS_DIR}/run.sh /opt/cron-agent/run.sh
COPY ${SCRIPTS_DIR}/logrotate-agent.conf /opt/cron-agent/logrotate-agent.conf
COPY ${SCRIPTS_DIR}/entrypoint.sh /entrypoint.sh
RUN chmod +x /opt/cron-agent/run.sh /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
