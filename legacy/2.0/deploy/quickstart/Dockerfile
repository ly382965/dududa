ARG ASTRBOT_BASE_IMAGE=soulter/astrbot:v4.27.5@sha256:1db1792902be5ccecfb907a720ae22b233ebdc958854d860fc73d7f95a720637
FROM ${ASTRBOT_BASE_IMAGE}

COPY deploy/patches/astrbot/4.26.2-openai-request-overrides.patch /tmp/astrbot-openai-request-overrides.patch
RUN cd /AstrBot \
    && patch --batch --forward -p1 < /tmp/astrbot-openai-request-overrides.patch \
    && rm /tmp/astrbot-openai-request-overrides.patch

COPY packages/dududa-agent /opt/dududa/dududa-agent
COPY services/mcp/campus-events /opt/dududa/campus-events-mcp
COPY services/mcp/college-notice /opt/dududa/college-notice-mcp
COPY services/mcp/icourse /opt/dududa/icourse-mcp
COPY services/mcp/library /opt/dududa/library-mcp
COPY services/mcp/local-recs /opt/dududa/local-recs-mcp
COPY services/mcp/notifai /opt/dududa/notifai-mcp
COPY services/mcp/training-plan /opt/dududa/training-plan-mcp
COPY services/mcp/ustc-campus /opt/dududa/ustc-campus-mcp
COPY services/mcp/console /opt/dududa/mcp-console
COPY services/mcp/unified-worker /opt/dududa/unified-mcp-worker
COPY apps/astrbot-plugins/astrbot_plugin_dududa_core/requirements.txt /opt/dududa/dududa-core-requirements.txt
RUN python -m pip install --no-cache-dir \
    "mcp==1.29.0" \
    "uv==0.12.1" \
    "opencv-python-headless==4.14.0.94" \
    "pyparsing==3.1.4" \
    -r /opt/dududa/dududa-core-requirements.txt \
    /opt/dududa/dududa-agent \
    /opt/dududa/campus-events-mcp \
    /opt/dududa/college-notice-mcp \
    /opt/dududa/icourse-mcp \
    /opt/dududa/library-mcp \
    /opt/dududa/local-recs-mcp \
    /opt/dududa/notifai-mcp \
    /opt/dududa/training-plan-mcp \
    /opt/dududa/ustc-campus-mcp \
    /opt/dududa/mcp-console \
    && uv sync --project /opt/dududa/unified-mcp-worker \
        --locked --no-dev --python 3.12 \
    && python -c 'import importlib.metadata; assert importlib.metadata.version("mcp") == "1.29.0"' \
    && /opt/dududa/unified-mcp-worker/.venv/bin/python -c \
        'import importlib.metadata; assert importlib.metadata.version("mcp") == "2.0.0"'

COPY deploy/patches/astrbot/4.27.5-bounded-provider-request.patch /tmp/astrbot-bounded-provider-request.patch
RUN cd /AstrBot \
    && patch --batch --forward -p1 < /tmp/astrbot-bounded-provider-request.patch \
    && rm /tmp/astrbot-bounded-provider-request.patch

# The submission image includes the files needed at first launch, so no host
# Python/Node/Git install or developer data bind mounts are required.
COPY ops/cli /opt/dududa/repository/ops/cli
COPY apps/astrbot-plugins /opt/dududa/repository/apps/astrbot-plugins
COPY services/mcp /opt/dududa/repository/services/mcp
COPY configs /opt/dududa/repository/configs
COPY configs /opt/dududa/config
COPY third_party /opt/dududa/repository/third_party
RUN python /opt/dududa/repository/ops/cli/install_plugins.py --owned-only --plugins-root /opt/dududa/bundled-plugins \
    && cp -a /opt/dududa/repository/third_party/submission-plugins/. /opt/dududa/bundled-plugins/
RUN find /opt/dududa/bundled-plugins -name requirements.txt -maxdepth 2 -print0 \
    | xargs -0 -r -I{} python -m pip install --no-cache-dir -r {}
COPY deploy/quickstart/setup.py /opt/dududa/quickstart/setup.py
LABEL org.opencontainers.image.title="Dududa submission runtime" \
      org.opencontainers.image.revision="2b525935fb2d6977e19765cc4283c73ec01b72ec"
