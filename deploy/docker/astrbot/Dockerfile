ARG ASTRBOT_BASE_IMAGE=m.daocloud.io/docker.io/soulter/astrbot@sha256:369164f8c2a063a6076203b8ef90be25e79be2d70c52c5317607035dece177ea
FROM ${ASTRBOT_BASE_IMAGE}

COPY deploy/patches/astrbot/4.26.2-openai-request-overrides.patch /tmp/astrbot-openai-request-overrides.patch
RUN cd /AstrBot \
    && patch --batch --forward -p1 < /tmp/astrbot-openai-request-overrides.patch \
    && rm /tmp/astrbot-openai-request-overrides.patch

COPY packages/dududa-agent /opt/dududa/dududa-agent
COPY services/mcp/icourse /opt/dududa/icourse-mcp
COPY services/mcp/ustc-campus /opt/dududa/ustc-campus-mcp
COPY services/mcp/console /opt/dududa/mcp-console
COPY services/mcp/unified-worker /opt/dududa/unified-mcp-worker
COPY apps/astrbot-plugins/astrbot_plugin_dududa_core/requirements.txt /opt/dududa/dududa-core-requirements.txt
RUN python -m pip install --no-cache-dir \
    "mcp==1.29.0" \
    "uv==0.12.1" \
    -r /opt/dududa/dududa-core-requirements.txt \
    /opt/dududa/dududa-agent \
    /opt/dududa/icourse-mcp \
    /opt/dududa/ustc-campus-mcp \
    /opt/dududa/mcp-console \
    && uv sync --project /opt/dududa/unified-mcp-worker \
        --locked --no-dev --python 3.12 \
    && python -c 'import importlib.metadata; assert importlib.metadata.version("mcp") == "1.29.0"' \
    && /opt/dududa/unified-mcp-worker/.venv/bin/python -c \
        'import importlib.metadata; assert importlib.metadata.version("mcp") == "2.0.0"'
